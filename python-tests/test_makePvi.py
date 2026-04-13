#from pathlib import Path
#import sys

# Allow importing MakePvi.py from ioc/scripts
#SCRIPT_DIR = Path(__file__).resolve().parents[1] / "ioc" / "scripts"
#sys.path.insert(0, str(SCRIPT_DIR))

from pvi.device import Group
import pytest
from typing import List
from xml.dom.minidom import Document, parseString
import yaml

from ioc.scripts import makePvi
from ioc.scripts.makePvi import GenICamModel, GenICamNode, PviModel


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
        <pFeature>EmptyCategoryIgnored</pFeature>
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

      <Category Name="EmptyCategoryIgnored">
        <Description>EmptyCategoryIgnored description</Description>
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
def genicam_model(example_xml: str) -> GenICamModel:
    return GenICamModel(example_xml)
    

@pytest.fixture
def pvi_model(genicam_model: GenICamModel) -> PviModel:
    instance_class: str ="Camera instance class"
    return PviModel(genicam_model, instance_class)


class TestUtilities:
    def test_sanitize_genicam_xml_with_non_xml_header(self):
        XML_WITH_CAMERA_ID = """CAMERA123
        <Root>
          <Whatever Name="Hello"/>
        </Root>
        """
        cleaned = makePvi.sanitize_genicam_xml(XML_WITH_CAMERA_ID)
        assert cleaned.startswith("<Root>")

    def test_sanitize_genicam_xml_without_non_xml_header(self):
        XML_WITH_CAMERA_ID = """
        <Root>
          <Whatever Name="Hello"/>
        </Root>
        """
        cleaned = makePvi.sanitize_genicam_xml(XML_WITH_CAMERA_ID)
        assert cleaned.startswith("<Root>")


class TestGenICamNode:
    def test_node_extract_description(self, xml_doc: Document):
        category_element = xml_doc.getElementsByTagName("Category")[1]
        node = GenICamNode(category_element)
        assert node.description == "AcquisitionCategory description"

    def test_node_extract_enum_choices(self, xml_doc: Document):
          enum_element = xml_doc.getElementsByTagName("Enumeration")[0]
          node = GenICamNode(enum_element)
          assert node.choices == ["Off", "On"]


class TestGenICamModel:
    def test_definition_nodes(self, genicam_model: GenICamModel):
        assert "AcquisitionCategory" in genicam_model.definition_nodes
        assert "ExposureTimeFeature" in genicam_model.definition_nodes

    def test_resolve_references(self, genicam_model: GenICamModel):
        acquisitionCategoryNode: GenICamNode = \
            genicam_model.definition_nodes["AcquisitionCategory"]
        assert len(acquisitionCategoryNode.children) == 5
        assert acquisitionCategoryNode.children[0].name == "ExposureTimeFeature"
        assert acquisitionCategoryNode.children[1].name == "GainFeature"
        assert acquisitionCategoryNode.children[2].name == "OffsetFeature"
        assert acquisitionCategoryNode.children[3].name == "EmptyCategoryIgnored"
        assert acquisitionCategoryNode.children[4].name == "ChildCategoryWithLeaf"

        childCategoryWithLeafNode: GenICamNode = \
            genicam_model.definition_nodes["ChildCategoryWithLeaf"]
        assert len(childCategoryWithLeafNode.children) == 1
        assert childCategoryWithLeafNode.children[0].name == "NestedFeature"

    def test_generate_epics_record_name_shorten_first_word_is_enough(self):
        record_name = GenICamModel._generate_epics_record_name(
            "SesquipedalianMeansLongWord",
            #12345678901234567890 
            {"ASignal": "GC_ASignal"},
            20,
            "GC_")
        
        assert record_name == "GC_SesMeansLongWord"
        #                      12345678901234567890 

    def test_generate_epics_record_name_shorten_long_words(self):
        record_name = GenICamModel._generate_epics_record_name(
            "ThisNameIsLongerThan20Characters",
            {"ASignal": "GC_ASignal"},
            20,
            "GC_")
        
        assert record_name == "GC_ThiNamIsLonThaCha"   

    def test_generate_epics_record_name_uniquify(self):
        record_name = GenICamModel._generate_epics_record_name(
            "ThisNameIsLongerThan20Characters",
            {"ASignal": "GC_ThiNamIsLonThaCha"},
            20,
            "GC_")
        
        assert record_name == "GC_ThiNamIsLonThaCh0"

    def test_generate_epics_record_name_uniquify_again(self):
        record_name = GenICamModel._generate_epics_record_name(
            "ThisNameIsLongerThan20Characters",
            {"Signal1": "GC_ThiNamIsLonThaCha", "Signal2": "GC_ThiNamIsLonThaCh0"},
            20,
            "GC_")
        
        assert record_name == "GC_ThiNamIsLonThaCh1"


class TestPviModel:
    def test_pvi_model(self, pvi_model: PviModel):
        groups: List[Group] = pvi_model.groups
        # Check groups
        group_names = [g.name for g in groups]
        assert "AcquisitionCategory" in group_names
        assert "ChildCategoryWithLeaf" in group_names
        assert "EmptyCategory" not in group_names

        # Check signals are generated
        acquisitionGroup = next(g for g in groups if g.name == "AcquisitionCategory")
        signal_names = [s.name for s in acquisitionGroup.children]
        assert set(signal_names) == \
            {"GCExpTimeFeature", "GCGainFeature", "GCOffsetFeature"}
        for signal in acquisitionGroup.children:
            assert signal.write_pv in ["$(P)$(R)GC_ExpTimeFeature", "$(P)$(R)GC_GainFeature", "$(P)$(R)GC_OffsetFeature"]
            assert signal.read_pv in ["$(P)$(R)GC_ExpTimeFeature_RBV", "$(P)$(R)GC_GainFeature_RBV", "$(P)$(R)GC_OffsetFeature_RBV"]

    def test_convert_genicam_xml_to_pvi_generates_yaml(self, example_xml: str):
        yaml_text = makePvi.convert_genicam_xml_to_pvi(
            example_xml,
            instance_class="Camera instance class",
            label="Camera test label"
        )
        print(yaml_text)
        # Load YAML to dict
        data = yaml.safe_load(yaml_text)
        assert isinstance(data, dict)
        # Device label
        assert data["label"] == "Camera test label"

        children = data["children"]
        assert len(children) == 1

        root = children[0]
        groups = root["children"]
        assert len(groups) == 2

        group_names = [g["name"] for g in groups]
        assert "AcquisitionCategory" in group_names
        assert "ChildCategoryWithLeaf" in group_names

        FirstGroup = next(g for g in groups if g["name"] == "AcquisitionCategory")

        assert FirstGroup["name"] == "AcquisitionCategory"
        # Signals inside group
        signal_names = [s["name"] for s in FirstGroup["children"]]
        assert set(signal_names) == {
            "GCExpTimeFeature",
            "GCGainFeature",
            "GCOffsetFeature"}
