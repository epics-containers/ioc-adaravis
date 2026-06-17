#!/bin/env python
from argparse import ArgumentParser, Namespace
from enum import Enum
from io import StringIO
from pathlib import Path
from pvi.device import Device, enforce_pascal_case, Grid, Group, SignalR, SignalRW, SignalW, SignalX, SubScreen
from pvi._yaml_utils import type_first, load_yaml
import re
from ruamel.yaml import YAML
import warnings
from xml.dom.minidom import Document, Element, parseString

DEBUG = False


def main():
    # Get parameters
    args: Namespace = get_cli_params()

    # Read input file
    genicam_input_file: Path = Path(args.input_xml)
    # Path.read_text closes file automatically
    file_contents: str = genicam_input_file.read_text()
    xml_text: str = sanitize_genicam_xml(file_contents)

    # Convert to PVI yaml
    yaml_text: str = convert_genicam_xml_to_pvi(
        xml_text,
        instance_class=args.instance_class,
        label=args.label,
        embed_in=args.embed_in,
        embedding_file_folder=args.output_folder)

    # Write output file
    output_folder: Path = Path(args.output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    # Path.write_text closes file automatically
    yaml_file: Path = output_folder / f"{args.instance_class}.pvi.device.yaml"
    yaml_file.write_text(yaml_text)
    print(f"Generated PVI YAML: {yaml_file}")


def get_cli_params() -> Namespace:
    """
    Parse CLI arguments and validate required fields.
    Returns:
        argparse.Namespace
    """
    parser: ArgumentParser = ArgumentParser()
    parser.add_argument("input_xml", help="Input XML file")
    parser.add_argument("output_folder", help="Output folder")
    parser.add_argument("--instance_class", dest="instance_class", required=True, help="Device class name, used as output file name root")
    parser.add_argument("--label", dest="label", required=True, help="Device instance ID, used for label")
    parser.add_argument("--embed_in", dest="embed_in", required=False, help="Root name of PVI yaml file that encloses the yaml from XML")

    args = parser.parse_args()

    return args


def sanitize_genicam_xml(xml_text: str) -> str:
    """
    A valid first line of an xml file will be optional whitespace followed by '<',
    But arv-tool might the camera id in the first line, resulting int invalid xml.
    This checks the first two lines and throw the first line away if it doesn't
    look like valid xml. If both first 2 lines are not valid xml then raise error.
    Returns:
        Cleaned XML text.
    """
    lines: list[str] = xml_text.splitlines(True)

    try:
        # Look at first 2 lines, locate the first one that looks like xml
        start_line = min(
            line_number for line_number in range(min(2, len(lines)))
                if lines[line_number].lstrip().startswith("<"))

    except ValueError:
        raise RuntimeError(
            "First two lines has no line that look likes valid XML:\n" + "".join(lines[:2]))

    return "".join(lines[start_line:]).lstrip()


def convert_genicam_xml_to_pvi(
        xml_text: str,
        instance_class: str,
        label: str,
        embed_in: str = "",
        embedding_file_folder: str = "") -> str:
    """
    Convert GenICam XML text into PVI YAML text,
    optionally enclose it as a subscreen in another PVI YAML.
     Args:
        xml_text: GenICam XML as string.
        instance_class: Device class name (used for YAML name/class fields).
        label: Device label (used for YAML label field).
        embed_in: Root name of PVI yaml file that encloses the yaml from XML.
        embedding_file_folder: Folder containing the embedding file.

    Returns:
        YAML text as string.
    """
    # Creating GenICam model
    genicam_model: GenICamModel = GenICamModel(xml_text)

    # Creating output model
    genicam_pvi_model: PviModel = PviModel(genicam_model, instance_class)

    # Build Device
    device: Device
    
    if not embed_in:
        # GenICam as alone device
        device = Device(label=label, children=genicam_pvi_model.groups)

    else:
        # GenICam embedded as subscreen
        enclosing_yaml = load_yaml(Path(f"{embedding_file_folder}{embed_in}.pvi.device.yaml"))
        device = Device.model_validate(enclosing_yaml)
        device.label = f"{device.label} + {label}"
        genicam_group: Group = Group(
            name="GenICam",
            layout=SubScreen(labelled=False),
            children=genicam_pvi_model.groups)
        device.children.append(genicam_group)

    # Return YAML from Device
    # Not using typ='safe' to default to typ='rt', ie, full round-trip YAML engine.
    # This outputs in insertion order.
    # Note, with rt there is no need for ym.sort_keys = False.
    output_yaml = YAML()
    # Use pure Python emitter instead of the C backend, slower but more consistent
    output_yaml.pure = True
    # This outputs like PyYaml
    # a:
    #   b: 1
    # instead of
    # a: {b: 1}
    output_yaml.default_flow_style = False
    stream = StringIO()
    data = device.model_dump(exclude_none=True)
    data.pop("type", None)  # remove top-level type "type: Device" because pvi format doesn't like it
    output_yaml.dump(type_first(data), stream)
    return stream.getvalue()


class AccessType(Enum):
    READ = "R"
    WRITE = "W"
    READWRITE = "RW"
    EXECUTE = "X"


class GenICamNode:
    def __init__(self, xml_element: Element) -> None:
        """
        Wrap a GenICam XML element into a Python Node object.
        Note the differentiation: "element" refers to XML,
        "node" refers to GenICam logical node

        Args:
            xml_element: an xml.dom.minidom.Element representing a
                         <Category>, <Float>, <Int>, <Enumeration>, etc
        """
        # Original XML element
        self.xml_element: Element = xml_element

        # Basic metadata
        self.name: str = xml_element.getAttribute("Name")
        self.description: str | None = self._extract_description()
        self.node_type: str = xml_element.nodeName # Raw from XML: Category, Float, Enumeration, etc
        self.access_type: AccessType | None = None # Parsed, to parse later
        self.is_category = self.node_type == "Category"
        self.is_signal: bool = self.node_type in [
            "Integer",
            "IntReg",
            "IntConverter",
            "IntSwissKnife",
            "Boolean",
            "Float",
            "Converter",
            "SwissKnife",
            "String",
            "StringReg",
            "Command",
            "Enumeration"]
        self.is_enum: bool = self.node_type == "Enumeration"
        self.epics_record_name: str | None = None

        # Children Node objects (from <pFeature> references)
        self.children: list["GenICamNode"] = []
        self.references_resolved: bool = False

        # Enumerations
        self.choices: list[str] | None = \
            self._extract_enum_choices() if self.node_type == "Enumeration" else None

    def _extract_description(self) -> str | None:
        # Do as below to look in immediate layer down only, rather than
        # desc_elements = self.xml_element.getElementsByTagName("Description")
        # if desc_elements and desc_elements[0].firstChild:
        #    return desc_elements[0].firstChild.nodeValue.strip()
        #return ""
        for child in self.xml_element.childNodes:
            if child.nodeName == "Description" and child.firstChild:
                return child.firstChild.nodeValue.strip()
        return None

    def _extract_enum_choices(self) -> list[str]:
        choices: list[str] = []
        # Similar search logic to _extract_description
        for child in self.xml_element.childNodes:
            if child.nodeName == "EnumEntry":
                name = child.getAttribute("Name")
                if name:
                    choices.append(name)
        return choices

    def get_child_text(self, *names: str) -> str | None:
        for child in self.xml_element.childNodes:
            if child.nodeName in names and child.firstChild:
                return child.firstChild.nodeValue.strip()
        return None

    def is_leaf(self) -> bool:
        if not self.references_resolved:
            raise RuntimeError(f"References not yet resolved for node {self.name}")
        return len(self.children) == 0

    def is_group(self) -> bool:
        """
        A group is a category that contains at least one leaf feature.
        """
        if not self.references_resolved:
            raise RuntimeError(f"References not yet resolved for node {self.name}")
        return self.is_category and any(child.is_leaf() for child in self.children)

    def resolve_children(
        self,
        definition_nodes_lookup: dict[str, "GenICamNode"]) -> None:
        """
        Populating self.children by resolving <pFeature> references.
        <pFeature> references are inside <Category > like this:
        <Category Name="EventID">
            <pFeature>EventAcquisitionStart</pFeature>
            <pFeature>EventAcquisitionEnd</pFeature>
        </Category>
        ...
        <Integer Name="EventAcquisitionStart">
        Note on syntax: If we have <pFeature>EventAcquisitionStart</pFeature> then
        feature_ref_element.firstChild is the DOM node/element containing the string EventAcquisitionStart
        and feature_ref.firstChild.nodeValue is the string EventAcquisitionStart
        """
        if self.references_resolved:
            return
        if not self.is_category:
            self.references_resolved = True
            return

        # Process the pFeature in the immediate next level down (don't recurse down).
        for child_element in self.xml_element.childNodes:
            if not(child_element.nodeName == "pFeature" and child_element.firstChild):
                continue

            feature_name = child_element.firstChild.nodeValue.strip()
            referenced_definition_node = definition_nodes_lookup.get(feature_name)
            if referenced_definition_node and referenced_definition_node not in self.children:
                self.children.append(referenced_definition_node)

        self.references_resolved = True
   
    def _determine_access_type(
        self,
        definition_nodes_lookup: dict[str, "GenICamNode"],
        visited: set[str]) -> AccessType | None:
        """
        Recursive helper equivalent to makeDb.py:is_node_readonly()
        """
        if self.name in visited:
            raise RuntimeError(f"Circular access dependency involving {self.name}")

        visited.add(self.name)

        if self.node_type == "Command":
            return AccessType.EXECUTE
        
        if not self.is_signal:
            return None

        # The ordering 1, 2, 3 below mirrors  makeDb.py
        # 1. Directly determined via AccessMode/ImposedAccessMode
        access_mode = self.get_child_text("AccessMode", "ImposedAccessMode")
        if access_mode:
            access_mode = access_mode.strip().upper()
            if access_mode in ("RO", "READONLY"):
                return AccessType.READ
            
            if access_mode in ("WO", "WRITEONLY"):
                return AccessType.WRITE
            
            if access_mode in ("RW", "READWRITE"):
                return AccessType.READWRITE

        # 2. Indirectly determined via pValue reference
        referenced_name = self.get_child_text("pValue")
        if referenced_name:

            referenced_node = definition_nodes_lookup.get(referenced_name)
            if referenced_node is None:
                raise RuntimeError(
                    f"{self.name}, pValue '{referenced_name}': target does not exist")

            return referenced_node._determine_access_type(
                definition_nodes_lookup,
                visited)

        # 3. SwissKnife special case
        if self.node_type in ("SwissKnife", "IntSwissKnife"):
            return AccessType.READ

        warnings.warn(
            f"Defaulting access type to READWRITE for {self.name} ({self.node_type})")
        return AccessType.READWRITE

    def set_access_type(
        self,
        definition_nodes_lookup: dict[str, "GenICamNode"]) -> None:
        """
        Public entry point called once by GenICamModel.
        """
        if self.is_signal and self.access_type is None:
            self.access_type = self._determine_access_type(
                definition_nodes_lookup,
                visited=set())

    def __repr__(self) -> str:
        return f"Node({self.name}, {self.node_type})"


class GenICamModel:
    """Parses and resolves references for GenICam XML."""

    def __init__(
            self,
            xml_text: str,
            epics_record_name_max_length: int = 20,
            epics_record_name_prefix: str = "GC_"):
        self.doc: Document = parseString(xml_text)
        self.definition_nodes: dict[str, GenICamNode] = self._build_definition_nodes()
        self._resolve_references()
        self._set_access_type_for_nodes()
        for node in self.definition_nodes.values():
            if node.is_signal and node.access_type is None:
                raise RuntimeError(f"Signal node {node.name} has no access type")

        self.epics_record_name_max_length: int = epics_record_name_max_length
        self.epics_record_name_prefix: str = epics_record_name_prefix
        self.epics_record_names: dict[str, str] = self._build_epics_record_names()

    def _build_definition_nodes(self) -> dict[str, GenICamNode]:
        """
        Extract all GenICam definition nodes, wrap them as Node objects and
        add them to a dictionary.
        Definition nodes are xml elements that look like this, we take them:
        <NodeType Name="My name" ...>
        Elements that look like below are reference nodes, we don't process them here:
        <pFeature>My name</pFeature>
        """
        lookup: dict[str, GenICamNode] = {}
        root_element: Element = self.doc.documentElement

        for xml_element in root_element.getElementsByTagName("*"):
            name: str = xml_element.getAttribute("Name")
            if name:
                lookup[name] = GenICamNode(xml_element)

        return lookup

    def _resolve_references(self) -> None:
        """
        Populate each node's children by resolving <pFeature> references.
        """
        for definition_node in self.definition_nodes.values():
            definition_node.resolve_children(self.definition_nodes)

    def _set_access_type_for_nodes(self) -> None:  
        for node in self.definition_nodes.values():
            node.set_access_type(self.definition_nodes)

    def _build_epics_record_names(self) -> dict[str, str]:
        epics_record_names: dict[str, str] = {}

        # Need to iterate over self.definition_nodes in an ordered way so that
        # the ouput is deterministic
        for node in sorted(self.definition_nodes.values(), key=lambda n: n.name):
            epics_record_name: str = GenICamModel._generate_epics_record_name(
                node.name,
                epics_record_names,
                self.epics_record_name_max_length,
                self.epics_record_name_prefix
            )
            epics_record_names[node.name] = epics_record_name
            node.epics_record_name = epics_record_name

        return epics_record_names

    @staticmethod
    def _generate_epics_record_name(
        name: str,
        epics_record_names: dict[str, str],
        max_length: int,
        epics_record_name_prefix: str
    ) -> str:
        """
        Generate epics record name so can generate PVs that correspond to what we have in epics.
        This replicate the logic in MakeDb.
        """

        record_name = f"{epics_record_name_prefix}{name}"

        # Step 1: Progressively truncating constituent “words” to 3 characters, stop if
        # string is short enough
        if len(record_name) > max_length:
            words: list[str] = re.findall(r"[a-zA-Z][^A-Z]*", record_name)

            for ii in range(len(words)):
                word = words[ii]
                if len(word) > 3:
                    words[ii] = word[:3]
                    record_name = "".join(words)
                    if len(record_name) <= max_length:
                        break

        # Step 2: If still too long, truncate
        if len(record_name) > max_length:
            record_name = record_name[:max_length]

        # Step 3: Ensure uniqueness
        ii = 0
        existing_values = set(epics_record_names.values())
        while record_name in existing_values:
            uniquifying_suffix = str(ii)
            record_name = record_name[: max_length - len(uniquifying_suffix)] + uniquifying_suffix
            ii += 1

        return record_name


class PviModel:
    """Creates PVI model whose groups property can be used by pvi.device.Device."""
    def __init__(self, genicam_model: GenICamModel, instance_class: str):
        self.groups: list[Group] = \
            PviModel._build_pvi_groups(genicam_model.definition_nodes, instance_class)
        # tree is just all the groups nested in a top group
        self.tree: Group = Group(
            name=enforce_pascal_case(instance_class),
            layout=Grid(),
            children=self.groups
        )

    @staticmethod
    def make_pv(name: str, suffix: str = "") -> str:
        return f"$(P)$(R){name}{suffix}"

    @staticmethod
    def make_signal(node: GenICamNode)-> SignalR | SignalRW | SignalW | SignalX:
        signal_name = enforce_pascal_case(node.epics_record_name)
        signal_description = node.description

        read_widget={"type": "TextRead"}

        if node.is_enum and node.choices:
            write_widget = {"type": "ComboBox"}
        else:
            # If not enum or no choices then use TextWrite
            write_widget = {"type": "TextWrite"}

        match node.access_type:

            case AccessType.EXECUTE:
                return SignalX(
                    name=signal_name,
                    description=signal_description,
                    write_pv=PviModel.make_pv(node.epics_record_name))

            case AccessType.READ:
                return SignalR(
                    name=signal_name,
                    description=signal_description,
                    read_pv=PviModel.make_pv(node.epics_record_name, "_RBV"),
                    read_widget=read_widget)

            case AccessType.WRITE:
                return SignalW(
                    name=signal_name,
                    description=signal_description,
                    write_pv=PviModel.make_pv(node.epics_record_name),
                    write_widget=write_widget)

            case AccessType.READWRITE:
                return SignalRW(
                    name=signal_name,
                    description=signal_description,
                    read_pv=PviModel.make_pv(node.epics_record_name, "_RBV"),
                    read_widget=read_widget,
                    write_pv=PviModel.make_pv(node.epics_record_name),
                    write_widget=write_widget)

        raise RuntimeError(
            f"Unexpected access type {node.access_type} for node {node.name}")

    @staticmethod
    def _build_pvi_groups(definition_nodes: dict[str, GenICamNode], instance_class: str) -> list[Group]:
        groups: list[Group] = []

        # Sort to make sure consistent test results
        for node in sorted(definition_nodes.values(), key=lambda n: n.name):
            # Select group nodes
            if not node.is_group():
                continue

            # Select group's children that are not category, these are leaves
            non_category_children = [
                child for child in node.children if not child.is_category]

            if not non_category_children:
                continue

            # Create signals from leaves
            signals: list[SignalR | SignalRW | SignalW | SignalX] = [
                PviModel.make_signal(leaf) for leaf in non_category_children if leaf.is_signal]

            group_name = enforce_pascal_case(node.name)
            group_description = node.description
            groups.append(
                Group(
                    name= group_name,
                    description=group_description,
                    children=signals,
                    layout=Grid()))

        # In case no categories produced groups
        if not groups:
            signals: list[SignalR | SignalRW | SignalW | SignalX] = []
            # Sort to make sure consistent test results
            for node in sorted(definition_nodes.values(), key=lambda n: n.name):
                if not node.is_category and node.is_signal:
                    signals.append(PviModel.make_signal(node))

            if signals:
                default_name = enforce_pascal_case(instance_class)
                groups = [Group(
                    name=default_name,
                    children=signals,
                    layout=Grid())]

        return groups


if __name__ == "__main__":
    main()
