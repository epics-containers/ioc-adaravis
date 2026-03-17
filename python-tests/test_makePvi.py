from pathlib import Path
from pvi.device import Group, enforce_pascal_case
import pytest
import sys
from typing import Dict, List, Tuple
from xml.dom.minidom import Document, Element, parseString

# Allow importing MakePvi.py from ioc/scripts
SCRIPT_DIR = Path(__file__).resolve().parents[1] / "ioc" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import makePvi
from makePvi import Node


@pytest.fixture
def example_xml() -> str:
  return """
  <Root>
    <Category Name="HigherLevelCategoryIgnored">
      <pFeature>AcquisitionCategory</pFeature>
    </Category>

    <Category Name="AcquisitionCategory">
      <Description>AcquisitionCategory description</Description>
      <pFeature>ExposureTimeFeature</pFeature>
      <pFeature>GainFeature</pFeature>
      <pFeature>OffsetFeature</pFeature>
      <pFeature>ChildCategoryLeafIgnored</pFeature>
      <pFeature>ChildCategoryWithLeaf</pFeature>
    </Category>

    <Float Name="ExposureTimeFeature">
      <Description>ExposureTimeFeature description</Description>
    </Float>

    <Float Name="GainFeature">
      <Description>GainFeature description</Description>
    </Float>

    <Float Name="OffsetFeature">
      <Description>OffsetFeature description</Description>
    </Float>

    <Category Name="ChildCategoryLeafIgnored">
      <Description>ChildCategoryLeafIgnored description</Description>
    </Category>

    <Category Name="ChildCategoryWithLeaf">
      <Description>ChildCategoryWithLeaf description</Description>
      <pFeature>NestedFeature</pFeature>
    </Category>

    <Float Name="NestedFeature">
      <Description>NestedFeature description</Description>
    </Float>

    <Enumeration Name="TriggerModeEnumeration">
      <Description>TriggerEnumeration description</Description>
      <EnumEntry Name="Off"/>
      <EnumEntry Name="On"/>
    </Enumeration>  
  </Root>
  """


@pytest.fixture
def xml_doc(example_xml: str) -> Document:
  return parseString(example_xml)


@pytest.fixture
def definition_nodes(xml_doc: Document) -> Dict[str, Node]:
  root: Element | None = xml_doc.documentElement
  return makePvi.build_definition_nodes_lookup(root)


@pytest.fixture
def definition_nodes_with_references_resolved(definition_nodes: Dict[str, Node]) -> Dict[str, Node]:
  makePvi.resolve_references(definition_nodes)
  return definition_nodes


def test_sanitize_genicam_xml_with_non_xml_header():
  XML_WITH_CAMERA_ID = """CAMERA123
  <Root>
    <Whatever Name="Hello"/>
  </Root>
  """
  cleaned = makePvi.sanitize_genicam_xml(XML_WITH_CAMERA_ID)
  assert cleaned.startswith("<Root>")


def test_sanitize_genicam_xml_without_non_xml_header():
  XML_WITH_CAMERA_ID = """
  <Root>
    <Whatever Name="Hello"/>
  </Root>
  """
  cleaned = makePvi.sanitize_genicam_xml(XML_WITH_CAMERA_ID)
  assert cleaned.startswith("<Root>")


def test_node_extract_description(xml_doc: Document):
  category_element = xml_doc.getElementsByTagName("Category")[1]
  node = makePvi.Node(category_element)
  assert node.description == "AcquisitionCategory description"


def test_node_extract_enum_choices(xml_doc: Document):
    enum_element = xml_doc.getElementsByTagName("Enumeration")[0]
    node = makePvi.Node(enum_element)
    assert node.choices == ["Off", "On"]


def test_build_definition_nodes_lookup(definition_nodes: Dict[str, Node]):
    assert "AcquisitionCategory" in definition_nodes
    assert "ExposureTimeFeature" in definition_nodes


def test_resolve_references(definition_nodes_with_references_resolved: Dict[str, Node]):
    acquisitionCategoryNode: Node = \
      definition_nodes_with_references_resolved["AcquisitionCategory"]
    assert len(acquisitionCategoryNode.children) == 5
    assert acquisitionCategoryNode.children[0].name == "ExposureTimeFeature"
    assert acquisitionCategoryNode.children[1].name == "GainFeature"
    assert acquisitionCategoryNode.children[2].name == "OffsetFeature"
    assert acquisitionCategoryNode.children[3].name == "ChildCategoryLeafIgnored"
    assert acquisitionCategoryNode.children[4].name == "ChildCategoryWithLeaf"

    childCategoryWithLeafNode: Node = \
      definition_nodes_with_references_resolved["ChildCategoryWithLeaf"]
    assert len(childCategoryWithLeafNode.children) == 1
    assert childCategoryWithLeafNode.children[0].name == "NestedFeature"


def test_build_pvi_groups(definition_nodes_with_references_resolved: Dict[str, Node]):
    groups: List[Group] = makePvi.build_pvi_groups(definition_nodes_with_references_resolved)

    # Should only include AcquisitionCategory, not EmptyCategory
    group_names = [g.name for g in groups]
    assert enforce_pascal_case("AcquisitionCategory") in group_names
    assert enforce_pascal_case("EmptyCategory") not in group_names

    # Check signals are generated
    group = next(g for g in groups if g.name == enforce_pascal_case("AcquisitionCategory"))
    signal_names = [s.name for s in group.children]
    assert set(signal_names) == {enforce_pascal_case("ExposureTimeFeature"), enforce_pascal_case("GainFeature"), enforce_pascal_case("OffsetFeature")}
    for signal in group.children:
        assert signal.write_pv in ["ExposureTimeFeature", "GainFeature", "OffsetFeature"]
        assert signal.read_pv in ["ExposureTimeFeature_RBV", "GainFeature_RBV", "OffsetFeature_RBV"]
