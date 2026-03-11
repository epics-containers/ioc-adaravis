#!/bin/env python
import sys
sys.path.ap
from xml.dom.minidom import Element, parseString
from optparse import OptionParser

from pvi.device import Device
from typing import Dict, List, Optional

# Huy: add
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
        desc_nodes = self.xml_element.getElementsByTagName("Description")
        if desc_nodes and desc_nodes[0].firstChild:
            return desc_nodes[0].firstChild.nodeValue.strip()
        return ""

    def _extract_enum_choices(self) -> List[str]:
        choices: List[str] = []
        for enum_entry in self.xml_element.getElementsByTagName("EnumEntry"):
            choices.append(enum_entry.getAttribute("Name"))
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

    def __repr__(self) -> str:
            return f"Node({self.name}, {self.node_type})"    


# Huy: add
def build_definition_nodes_lookup(root_element: Element) -> Dict[str, Node]:
    """
    Extract all GenICam definition nodes, wrap them as Node objects and
    add them to a dictionary.
    Definition nodes are xml elements that look like this, we take them:
    <NodeType Name="My name" ...>
    Nodes that look like below are reference nodes, we don't process them here:
    <pFeature>My name</pFeature> 
    """
    definition_nodes_lookup: Dict[str, Node] = {}

    for xml_element in root_element.getElementsByTagName("*"):
        if xml_element.hasAttribute("Name"):
            name = xml_element.getAttribute("Name")
            definition_nodes_lookup[name] = Node(xml_element)

    return definition_nodes_lookup


# Huy: add
def resolve_references(definition_nodes_lookup: Dict[str, Node]) -> None:
    """
    Populate each Node.children in definition_nodes_lookup by resolving <pFeature> references.
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
    for definition_node in definition_nodes_lookup.values():
        if definition_node.is_category():
            # Process the pFeature in the next level down (don't recurse down).
            for child_element in definition_node.xml_element.childNodes:
                if child_element.nodeName == "pFeature" and child_element.firstChild:
                    feature_name = child_element.firstChild.nodeValue.strip()
                    referenced_definition_node = definition_nodes_lookup.get(feature_name)
                    if referenced_definition_node:
                        definition_node.children.append(referenced_definition_node)

        definition_node.references_resolved = True


# Huy: add
def print_pvi_groups(definition_nodes_lookup: Dict[str, Node]) -> None:
    """
    Print all two-level groups and their leaf signals.
    """
    for definition_node in definition_nodes_lookup.values():
        if definition_node.is_group():
            print(f"PVI GROUP: {definition_node.name}")
            for child in definition_node.children:
                if child.is_leaf():
                    print(f"  SIGNAL: {child.name} [{child.node_type}]")


#Huy: add
def build_pvi_device(device_name: str, definition_nodes_lookup: Dict[str, Node]) -> Device:
    device = Device(device_name)

    for definition_node in definition_nodes_lookup.values():
        if definition_node.is_group():
            group_name = definition_node.name
            # Create a group in PVI
            device.add_group(group_name)
            # Add leaf signals in this group
            for child in definition_node.children:
                if child.is_leaf():
                    # Use name, type, description from XML attributes
                    desc = child.xml_element.getAttribute("Description") or ""
                    device.add_signal(
                        group_name=group_name,
                        signal_name=child.name,
                        signal_type=child.node_type,
                        description=desc
                    )

    return device


# -------------------------
# Main script entry
# -------------------------
def main(xml_path: str, device_name: str, yaml_out_path: str) -> None:
    dom = parse(xml_path)
    root = dom.documentElement

    # Build GenICam nodes
    definition_nodes_lookup = build_definition_nodes_lookup(root)

    # Resolve <pFeature> references
    resolve_references(definition_nodes_lookup)

    # Create PVI device
    device = build_pvi_device(device_name, definition_nodes_lookup)

    # Serialize to YAML
    device.to_yaml(yaml_out_path)
    print(f"PVI YAML written to {yaml_out_path}")



# Huy: add
def debug_print_pvi_mapping(definition_node: Node,
                            indent: int = 0,
                            visited: set[str] | None = None) -> None:
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


# Huy: add
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

# Huy: keep?: return only XML element node
# function to read element children of a node
def elements(node):
    return [n for n in node.childNodes if n.nodeType == n.ELEMENT_NODE]  


# Huy: keep?: extract text from XML nodes like
# a function to read the text children of a node
def getText(node):
    return ''.join([n.data for n in node.childNodes if n.nodeType == n.TEXT_NODE])





# Huy: add get metadata
def get_description(node):
    for child in elements(node):
        if child.nodeName == "Description":
            return getText(child)
    return ""


# Huy: add get metadata
def get_enum_values(node):
    values = []
    for child in elements(node):
        if child.nodeName == "EnumEntry":
            name = child.getAttribute("Name")
            values.append(name)
    return values


# Huy: add build hierarchical groups recursively using Device API
def build_group(device, category_name, lookup, done):
    """
    Build PVI groups for a GenICam XML category such that:
    - Only the lowest-level features (non-category nodes) become signals.
    - Only the immediate parent category of these leaf features becomes a group.
    - Ancestor categories containing only other categories are skipped.
    - Higher-level categories are skipped.
    
    Args:
        device: The root Device object or parent Group.
        category_name: Name of the current Category to process.
        lookup: Dict mapping feature/category names to XML nodes.
        done: Set of nodes already processed to avoid duplicates.

    Recursive traversal via <pFeature> references:
        If a <pFeature> points to another Category, recurse into it to find leaf features.
        Leaf <pFeatures> become PVI signals.
    """
    node = lookup.get(category_name)
    if node is None:
        return

    # Collect leaf features directly under this category
    leaf_features = []

    child_nodes = elements(node)
    for child_node in child_nodes:
        if child_node.nodeName != "pFeature":
            continue

        feature_name = getText(child_node)
        feature_node = lookup.get(feature_name)
        if feature_node is None or feature_node in done:
            continue

        # If this pFeature references a Category, recurse into it
        if feature_node.nodeName == "Category":
            build_group(device, feature_name, lookup, done)
        else:
            # Leaf feature
            leaf_features.append(feature_node)

    # Only create a group if this category has leaf features directly under it
    if leaf_features:
        group = device.add_group(category_name)
        for leaf in leaf_features:
            desc = get_description(leaf)
            node_type = leaf.nodeName

            if node_type == "Enumeration":
                choices = get_enum_values(leaf)
                group.add_signal(
                    name=leaf.getAttribute("Name"),
                    dtype="enum",
                    description=desc,
                    choices=choices
                )
            else:
                group.add_signal(
                    name=leaf.getAttribute("Name"),
                    dtype="float" if node_type == "Float" else "int",
                    description=desc
                )
            done.add(leaf)


# Huy: add
def map_signal_type(node):

    t = node.nodeName

    if t in ["Integer", "Float"]:
        return "number"

    if t == "Boolean":
        return "boolean"

    if t == "Enumeration":
        return "enum"

    if t == "Command":
        return "command"

    return "string"


# Huy: add
def build_device(device_name, category_trees):
    device = Device(name=device_name)

    def add_group(device_or_parent, cat):
        group = device_or_parent.add_group(cat["name"])
        # add signals
        for fnode in cat["features"]:
            fname = fnode.getAttribute("Name")
            ftype = map_signal_type(fnode)
            group.add_signal(fname, ftype)
        # recursively add subcategories
        for subcat in cat["subcategories"]:
            add_group(group, subcat)

    for cat in category_trees:
        add_group(device, cat)

    return device


# Huy: add
def main(xml_file, yaml_file):
    # Check the first two lines of the feature xml file to see if arv-tool left
    # the camera id there, thus creating an unparsable file
    # Throw it away if it doesn't look like valid xml
    # A valid first line of an xml file will be optional whitespace followed by '<'
    genicam_lines = open(xml_file).readlines()
    try:
        start_line = min(i for i in range(2) if genicam_lines[i].lstrip().startswith("<"))
    except:
        print("Neither of these lines looks like valid XML:")
        print("".join(genicam_lines[:2]))
        sys.exit(1)

    # parse xml file to dom object
    xml_root = parseString("".join(genicam_lines[start_line:]).lstrip())


    doc = parse(xml_file)
    root = doc.documentElement
    lookup = build_definition_nodes_lookup(root)

    categories = [name for name, node in lookup.items() if node.nodeName == "Category"]
    category_trees = [build_category_tree(c, lookup) for c in categories]

    device = build_device("GenICamDevice", category_trees)

    # write YAML
    device.write_yaml(yaml_file)


# Huy: add
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python makePvi.py <GenICam XML> <output YAML>")
        sys.exit(1)

    xml_file = sys.argv[1]
    yaml_file = sys.argv[2]

    main(xml_file, yaml_file)


# parse args
parser = OptionParser("""%prog <xmlFile> <templateFile>
This script parses a GenICam xml file and creates an EPICS database template""")
parser.add_option("", "--devInt64",
                  action="store_true", dest="devInt64", default=False,
                  help="use int64in and int64out records. Requires at least EPICS base 3.16.1 or EPICS 7.")
options, args = parser.parse_args()
if len(args) != 2:
    parser.error("Incorrect number of arguments")
if (options.devInt64):
  GCIntegerInputRecordType = "int64in"
  GCIntegerOutputRecordType = "int64out"
else:
  GCIntegerInputRecordType = "ai"
  GCIntegerOutputRecordType = "ao"

# Check the first two lines of the feature xml file to see if arv-tool left
# the camera id there, thus creating an unparsable file
# Throw it away if it doesn't look like valid xml
# A valid first line of an xml file will be optional whitespace followed by '<'
genicam_lines = open(args[0]).readlines()
try:
    start_line = min(i for i in range(2) if genicam_lines[i].lstrip().startswith("<"))
except:
    print("Neither of these lines looks like valid XML:")
    print("".join(genicam_lines[:2]))
    sys.exit(1)

# Huy: keep: creates the DOM tree
# parse xml file to dom object
xml_root = parseString("".join(genicam_lines[start_line:]).lstrip())
db_filename = args[1]

# node lookup from nodeName -> node
lookup = {}
# lookup from nodeName -> recordName
records = {}
categories = []

# Huy: modify
# function to create a lookup table of nodes
def handle_node(node):
    if node.nodeName == "Group":
        for n in elements(node):
            handle_node(n)
    elif node.hasAttribute("Name"):
        name = str(node.getAttribute("Name"))
        lookup[name] = node
        # Add a leading GC_ to the name to prevent identical record names to those in ADBase.template
        recordName = "GC_" + name
        """
        if len(recordName) > 20:
            words=re.findall('[a-zA-Z][^A-Z]*', recordName)
            for i in range(len(words)):
                word = words[i]
                if (len(word) > 3):
                    word = word[:3]
                    words[i] = word
                    s = ''
                    recordName = s.join(words)
                    if (len(recordName) <= 20): break
        if len(recordName) > 20:                    
            recordName = recordName[:20]
        i = 0
        while recordName in records.values():
            recordName = recordName[:-len(str(i))] + str(i)
            i += 1
        """
        records[name] = recordName
        if node.nodeName == "Category":
            categories.append(name)
    elif node.nodeName != "StructReg":
        print("Node has no Name attribute", node)

# list of all nodes    
for node in elements(elements(xml_root)[0]):
    handle_node(node)

# Now make structure, [(title, [features...]), ...]
structure = []
doneNodes = []


"""
def handle_category(category):
    # making flat structure, so if its already there then don't do anything
    if category in [x[0] for x in structure]:
        return
    node = lookup[category]
    # for each child feature of this node
    features = []
    cgs = []
    for feature in elements(node):        
        if feature.nodeName == "pFeature":
            featureName = str(getText(feature))
            featureNode = lookup[featureName]
            if str(featureNode.nodeName) == "Category":
                cgs.append(featureName)
            else:
                if featureNode not in doneNodes:
                    features.append(featureNode)   
                    doneNodes.append(featureNode)
    if features:
        if len(features) > 32:
            i = 1
            while features:
                structure.append((category+str(i), features[:32]))
                i += 1
                features = features[32:]
        else:            
            structure.append((category, features))
    for category in cgs:
        handle_category(category)
"""

# << Huy: add
categoryTrees = []

for category in categories:
    categoryTrees.append(build_category_tree(category))
# >>

"""
for category in categories:
    handle_category(category)
"""

# Spit out a database file
db_file = open(db_filename, "w")
stdout = sys.stdout
sys.stdout = db_file

# print(a header
print('# Macros:')
print('#% macro, P, Device Prefix')
print('#% macro, R, Device Suffix')
print('#% macro, PORT, Asyn Port name')
print('#% macro, TIMEOUT, Timeout, default=1')
print('#% macro, ADDR, Asyn Port address, default=0')
print()

# for each node
for node in doneNodes:
    nodeName = str(node.getAttribute("Name"))
    ro = False
    for n in elements(node):
        if str(n.nodeName) == "AccessMode" and getText(n) == "RO":
            ro = True
    if node.nodeName in ["Integer", "IntConverter", "IntSwissKnife"]:
        """
        print('record(%s, "$(P)$(R)%s_RBV") {' % (GCIntegerInputRecordType, records[nodeName]))
        print('  field(DTYP, "asynInt64")')
        print('  field(INP,  "@asyn($(PORT),$(ADDR=0),$(TIMEOUT=1))GC_I_%s")' % nodeName)
        print('  field(SCAN, "I/O Intr")')
        print('  field(DISA, "0")')
        print('}')
        print()
        """
        if ro:
            continue
        """        
        print('record(%s, "$(P)$(R)%s") {' % (GCIntegerOutputRecordType, records[nodeName]))
        print('  field(DTYP, "asynInt64")')
        print('  field(OUT,  "@asyn($(PORT),$(ADDR=0),$(TIMEOUT=1))GC_I_%s")' % nodeName)
        print('  field(DISA, "0")')
        print('}')
        print()
        """
    elif node.nodeName in ["Boolean"]:
        """
        print('record(bi, "$(P)$(R)%s_RBV") {' % records[nodeName])
        print('  field(DTYP, "asynInt32")')
        print('  field(INP,  "@asyn($(PORT),$(ADDR=0),$(TIMEOUT=1))GC_B_%s")' % nodeName)
        print('  field(SCAN, "I/O Intr")')
        print('  field(ZNAM, "No")')
        print('  field(ONAM, "Yes")'                        )
        print('  field(DISA, "0")')
        print('}')
        print()
        """
        if ro:
            continue
        """        
        print('record(bo, "$(P)$(R)%s") {' % records[nodeName])
        print('  field(DTYP, "asynInt32")')
        print('  field(OUT,  "@asyn($(PORT),$(ADDR=0),$(TIMEOUT=1))GC_B_%s")' % nodeName)
        print('  field(ZNAM, "No")')
        print('  field(ONAM, "Yes")'                                )
        print('  field(DISA, "0")')
        print('}')
        print()
        """
    elif node.nodeName in ["Float", "Converter", "SwissKnife"]:
        """
        print('record(ai, "$(P)$(R)%s_RBV") {' % records[nodeName])
        print('  field(DTYP, "asynFloat64")')
        print('  field(INP,  "@asyn($(PORT),$(ADDR=0),$(TIMEOUT=1))GC_D_%s")' % nodeName)
        print('  field(PREC, "3")'        )
        print('  field(SCAN, "I/O Intr")')
        print('  field(DISA, "0")')
        print('}')
        print()
        """
        if ro:
            continue
        """   
        print('record(ao, "$(P)$(R)%s") {' % records[nodeName])
        print('  field(DTYP, "asynFloat64")')
        print('  field(OUT,  "@asyn($(PORT),$(ADDR=0),$(TIMEOUT=1))GC_D_%s")' % nodeName)
        print('  field(PREC, "3")')
        print('  field(DISA, "0")')
        print('}')
        print()
        """
    elif node.nodeName in ["StringReg"]:
        pass
        """
        print('record(stringin, "$(P)$(R)%s_RBV") {' % records[nodeName])
        print('  field(DTYP, "asynOctetRead")')
        print('  field(INP,  "@asyn($(PORT),$(ADDR=0),$(TIMEOUT=1))GC_S_%s")' % nodeName)
        print('  field(SCAN, "I/O Intr")')
        print('  field(DISA, "0")')
        print('}')
        print()
        """
    elif node.nodeName in ["Command"]:
        pass
        """
        print('record(longout, "$(P)$(R)%s") {' % records[nodeName])
        print('  field(DTYP, "asynInt32")')
        print('  field(OUT,  "@asyn($(PORT),$(ADDR=0),$(TIMEOUT=1))GC_C_%s")' % nodeName)
        print('  field(DISA, "0")')
        print('}')
        print()
        """
    elif node.nodeName in ["Enumeration"]:
        enumerations = ""
        i = 0
        defaultVal = "0"
        epicsId = ["ZR", "ON", "TW", "TH", "FR", "FV", "SX", "SV", "EI", "NI", "TE", "EL", "TV", "TT", "FT", "FF"]
        for n in elements(node):
            if str(n.nodeName) == "EnumEntry":
                if i >= len(epicsId):
                    print("More than 16 enum entries for %s mbbi record, discarding additional options." % nodeName, file=sys.stderr)
                    print("   If needed, edit the Enumeration tag for %s to select the 16 you want." % nodeName, file=sys.stderr)
                    break
                name = str(n.getAttribute("Name"))
                enumerations += '  field(%sST, "%s")\n' %(epicsId[i], name[:16])
                value = [x for x in elements(n) if str(x.nodeName) == "Value"]
                assert value, "EnumEntry %s in node %s doesn't have a value" %(name, nodeName)                
                if i == 0:
                    defaultVal = getText(value[0])
                enumerations += '  field(%sVL, "%s")\n' %(epicsId[i], getText(value[0]))
                i += 1                
        """
        print('record(mbbi, "$(P)$(R)%s_RBV") {' % records[nodeName])
        print('  field(DTYP, "asynInt32")')
        print('  field(INP,  "@asyn($(PORT),$(ADDR=0),$(TIMEOUT=1))GC_E_%s")' % nodeName)
        print(enumerations, end="")
        print('  field(SCAN, "I/O Intr")')
        print('  field(DISA, "0")')
        print('}')
        print()
        """
        if ro:
            continue
        """       
        print('record(mbbo, "$(P)$(R)%s") {' % records[nodeName])
        print('  field(DTYP, "asynInt32")')
        print('  field(OUT,  "@asyn($(PORT),$(ADDR=0),$(TIMEOUT=1))GC_E_%s")' % nodeName)
        print('  field(DOL,  "%s")' % defaultVal)
        print(enumerations, end="")
        print('  field(DISA, "0")')
        print('}')
        print()
        """
    else:
        print("Don't know what to do with %s" % node.nodeName, file=sys.stderr)
    
# tidy up
db_file.close()     
sys.stdout = stdout

#endObjectProperties""" % globals() )

