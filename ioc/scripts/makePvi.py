#!/bin/env python
import sys
sys.path.ap
from xml.dom.minidom import Document, Element, parseString
from optparse import OptionParser, Values
from pathlib import Path

from pvi.device import Device
from typing import Dict, List, Optional, Tuple

DEBUG = False

class Node:
    def __init__(self, xml_element: Element) -> None:
        """
        Wrap a GenICam XML element into a Python Node object.
        Note the differentiation: "element" refers to XML,
        "node" refers to GenICam logical node

        Args:
            xml_element: an xml.dom.minidom.Element representing a 
                         <Category>, <Float>, <Int>, <Enumeration>, etc.
        """
        # Original XML element
        self.xml_element: Element = xml_element

        # Basic metadata
        self.name: str = xml_element.getAttribute("Name")
        self.node_type: str = xml_element.nodeName  # Category, Float, Int, Enumeration
        self.description: str = self._extract_description()

        # Children Node objects (from <pFeature> references)
        self.children: List["Node"] = []
        self.references_resolved: bool = False

        # Enumerations
        self.choices: Optional[List[str]] = \
            self._extract_enum_choices() if self.node_type == "Enumeration" else None

    def _extract_description(self) -> str:
        # Do as below to look in immediate layer down only, rather than
        # desc_elements = self.xml_element.getElementsByTagName("Description")
        # if desc_elements and desc_elements[0].firstChild:
        #    return desc_elements[0].firstChild.nodeValue.strip()
        #return ""
        for child in self.xml_element.childNodes:
            if child.nodeName == "Description" and child.firstChild:
                return child.firstChild.nodeValue.strip()
        return ""

    def _extract_enum_choices(self) -> List[str]:
        choices: List[str] = []
        # Do as below to look in immediate layer down only, rather than
        # for enum_entry in self.xml_element.getElementsByTagName("EnumEntry"):
        #     choices.append(enum_entry.getAttribute("Name"))
        # return choices
        for child in self.xml_element.childNodes:
            if child.nodeName == "EnumEntry":
                name = child.getAttribute("Name")
                if name:
                    choices.append(name)
        return choices

    def is_category(self) -> bool:
        return self.node_type == "Category"

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
        return self.is_category() and any(child.is_leaf() for child in self.children)

    def resolve_children(self, definition_nodes_lookup: Dict[str, "Node"]) -> None:
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
        if not self.is_category():
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

    def __repr__(self) -> str:
            return f"Node({self.name}, {self.node_type})"    


def build_definition_nodes_lookup(root_element: Element) -> Dict[str, Node]:
    """
    Extract all GenICam definition nodes, wrap them as Node objects and
    add them to a dictionary.
    Definition nodes are xml elements that look like this, we take them:
    <NodeType Name="My name" ...>
    Elements that look like below are reference nodes, we don't process them here:
    <pFeature>My name</pFeature> 
    """
    lookup: Dict[str, Node] = {}

    for xml_element in root_element.getElementsByTagName("*"):
        name: str = xml_element.getAttribute("Name")
        if name:
            lookup[name] = Node(xml_element)

    return lookup


def resolve_references(definition_nodes_lookup: Dict[str, Node]) -> None:
    """
    Populate each node's children in definition_nodes_lookup by resolving <pFeature> references.
    """
    for definition_node in definition_nodes_lookup.values():
        definition_node.resolve_children(definition_nodes_lookup)


def build_pvi_groups(definition_nodes_lookup: Dict[str, Node]) -> List[Tuple[str, List[Node]]]:
    """
    Determine two-level PVI groups and their signals.
    Returns:
        List of tuples: (group_name, list of leaf Nodes in group)
    """
    groups: List[Tuple[str, List[Node]]] = []
    for node in definition_nodes_lookup.values():
        if not node.is_group():
            continue
        leaf_children: List[Node] = [child for child in node.children if not child.is_category()]
        if leaf_children:
            groups.append((node.name, leaf_children))
    return groups


def sanitize_genicam_xml(xml_text: str) -> str:
    """
    A valid first line of an xml file will be optional whitespace followed by '<',
    But arv-tool might the camera id in the first line, resulting int invalid xml.
    This checks the first two lines and throw the first line away if it doesn't
    look like valid xml. If both first 2 lines are not valid xml then raise error.
    Returns:
        Cleaned XML text.
    """
    lines: List[str] = xml_text.splitlines(True)

    try:
        # Look at first 2 lines, locate the first one that looks like xml
        start_line = min(
            line_number for line_number in range(min(2, len(lines))) if lines[line_number].lstrip().startswith("<")
        )
    except ValueError:
        raise RuntimeError(
            "First two lines has no line that look likes valid XML:\n" + "".join(lines[:2])
        )

    return "".join(lines[start_line:]).lstrip()


def convert_genicam_xml_to_pvi(xml_text: str, instance_class: str, label: str) -> str:
    """
    Convert GenICam XML text into PVI YAML text.
     Args:
        xml_text: GenICam XML as string.
        instance_class: Device class name (used for YAML name/class fields).
        label: Device label (used for YAML label field).

    Returns:
        YAML text as string.
    """

    doc: Document = parseString(xml_text)
    root_element: Element = doc.documentElement

    # Build Node graph and resolve references
    definition_nodes_lookup: Dict[str, Node] = build_definition_nodes_lookup(root_element)
    resolve_references(definition_nodes_lookup)

    # Build Device then populate groups/signals
    device: Device = Device(name=instance_class, class_=instance_class, label=label)

    # Build PVI groups (two-level: group + signals)
    groups = build_pvi_groups(definition_nodes_lookup)

    for group_name, leaf_nodes in groups:
        device.add_group(group_name)

        for leaf_node in leaf_nodes:
            device.add_signal(
                group_name=group_name,
                signal_name=leaf_node.name,
                signal_type=leaf_node.node_type,
                description=leaf_node.description
            )

    # Return YAML as string
    return device.to_yaml()


def get_cli_params() -> Tuple[Values, List[str]]:
    """
    Parse CLI arguments and validate required fields.
    Returns:
        Tuple[Values, List[str]]: (options, positional args)
    """
    usage: str = "usage: %prog [options] <input-xml> <output-folder>"
    parser: OptionParser = OptionParser(usage=usage)
    parser.add_option("--name", dest="instance_class", help="Device class name")
    parser.add_option("--label", dest="label", help="Device label")
    # Type hint doesn't like options, args: Tuple[Values, List[str]] = parser.parse_args()
    # so do as below
    options: Values
    args: List[str]
    options, args = parser.parse_args()

    if not options.instance_class or not options.label:
        parser.error("--name and --label are required")

    if len(args) != 2:
        parser.error("You must provide <input-xml> and <output-folder>")

    return options, args


def debug_print_pvi_groups(definition_nodes_lookup: Dict[str, Node]) -> None:
    """
    Print all two-level groups and their leaf signals.
    """
    for definition_node in definition_nodes_lookup.values():
        if definition_node.is_group():
            print(f"PVI GROUP: {definition_node.name}")
            for child in definition_node.children:
                if child.is_leaf():
                    print(f"  SIGNAL: {child.name} [{child.node_type}]")


def debug_print_pvi_mapping(definition_node: Node,
                            indent: int = 0,
                            visited: Optional[set[str]] = None) -> None:
    if visited is None:
        visited = set()
    if definition_node.name in visited:
        return
    visited.add(definition_node.name)
    if definition_node.is_category():
        leaf_children = [c for c in definition_node.children if not c.is_category()]
        marker = "[GROUP]" if leaf_children else "[SKIP]"
    else:
        marker = "[SIGNAL]"
    print("  " * indent + f"{marker} {definition_node.name} ({definition_node.node_type})")
    for child in definition_node.children:
        debug_print_pvi_mapping(child, indent + 1, visited)


def debug_print_all_pvi_mappings(definition_nodes_lookup: Dict[str, Node]) -> None:
    for definition_node in definition_nodes_lookup.values():
        if definition_node.is_category():
            debug_print_pvi_mapping(definition_node)
            print()


def debug_print_final_pvi(definition_nodes_lookup: Dict[str, Node]) -> None:
    """
    Print the final PVI groups and signals exactly as they will appear in YAML.
    """
    printed_signals: set[str] = set()
    for definition_node in definition_nodes_lookup.values():
        if not definition_node.is_category():
            continue
        # collect leaf features under this category
        leaf_features = []

        for child_node in definition_node.children:
            if not child_node.is_category():
                if child_node.name not in printed_signals:
                    leaf_features.append(child_node)

        if not leaf_features:
            continue

        print(f"\nGROUP: {definition_node.name}")

        for feature in leaf_features:
            printed_signals.add(feature.name)
            print(
                f"  SIGNAL: {feature.name} "
                f"[{feature.node_type}] "
                f"{'- ' + feature.description if feature.description else ''}"
            )


def main() -> None:
    # Get parameters
    # Type hint doesn't like options, args: Tuple[Values, List[str]] = parser.parse_args()
    # so do as below
    options: Values
    args: List[str]
    options, args = get_cli_params()

    # Read input file
    genicam_input_file: Path = Path(args[0])
    # Path.read_text closes file automatically
    xml_text: str = genicam_input_file.read_text()
 
    # Convert
    yaml_text: str = convert_genicam_xml_to_pvi(
        xml_text,
        instance_class=options.instance_class,
        label=options.label
    )

    # Write output file
    output_folder: Path = Path(args[1])
    output_folder.mkdir(parents=True, exist_ok=True)
    # Path.write_text closes file automatically
    yaml_file: Path = output_folder / f"{options.instance_class}.yaml"
    yaml_file.write_text(yaml_text)
    print(f"Generated PVI YAML: {yaml_file}")


if __name__ == "__main__":
    main()
