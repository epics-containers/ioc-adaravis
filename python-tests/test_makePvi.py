from pathlib import Path
import sys

# Allow importing makePvi.py from ioc/scripts
SCRIPT_DIR = Path(__file__).resolve().parents[1] / "ioc"
sys.path.insert(0, str(SCRIPT_DIR))

from pvi.device import Group, SignalX
import pytest
from xml.dom.minidom import Document, parseString
from ruamel.yaml import YAML

from scripts import makePvi
from scripts.makePvi import GenICamModel, GenICamNode, PviModel


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
        <AccessMode>RW</AccessMode>
      </Float>

      <Float Name="GainFeature">
        <Description>GainFeature description</Description>
        <ImposedAccessMode>WO</ImposedAccessMode>
      </Float>

      <Float Name="OffsetFeature">
        <Description>OffsetFeature description</Description>
        <ImposedAccessMode>WO</ImposedAccessMode>
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
        <ImposedAccessMode>WO</ImposedAccessMode>
      </Float>

      <Enumeration Name="TriggerModeEnumeration">
        <Description>TriggerEnumeration description</Description>
        <ImposedAccessMode>WO</ImposedAccessMode>
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
        groups: list[Group] = pvi_model.groups
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
            if signal.name == "GCExpTimeFeature":
                assert signal.write_pv in ["$(P)$(R)GC_ExpTimeFeature", "$(P)$(R)GC_GainFeature", "$(P)$(R)GC_OffsetFeature"]
                assert signal.read_pv in ["$(P)$(R)GC_ExpTimeFeature_RBV", "$(P)$(R)GC_GainFeature_RBV", "$(P)$(R)GC_OffsetFeature_RBV"]

    def test_command_generates_signalx(self):
        xml = """
        <Root>
        <Category Name="AcquisitionCategory">
            <pFeature>AcquisitionStart</pFeature>
        </Category>

        <Command Name="AcquisitionStart">
            <Description>Start acquisition</Description>
        </Command>
        </Root>
        """

        genicam_model: GenICamModel = GenICamModel(xml)
        pvi_model: PviModel = PviModel(genicam_model, "Camera")

        signal = pvi_model.groups[0].children[0]

        assert isinstance(signal, SignalX)
        assert signal.write_pv == "$(P)$(R)GC_AcquisitionStart"

    def test_filter_for_signals(self):
        xml = """
        <Root>
        <Category Name="AcquisitionCategory">
            <pFeature>IntegerSignal</pFeature>
            <pFeature>NotASignal</pFeature>
            <pFeature>IntRegSignal</pFeature>
            <pFeature>IntConSignal</pFeature>
            <pFeature>IntSwiKnifeSignal</pFeature>
            <pFeature>BooleanSignal</pFeature>
            <pFeature>FloatSignal</pFeature>
            <pFeature>ConverterSignal</pFeature>
            <pFeature>SwissKnifeSignal</pFeature>
            <pFeature>StringSignal</pFeature>
            <pFeature>StringRegSignal</pFeature>
            <pFeature>CommandSignal</pFeature>
            <pFeature>EnumerationSignal</pFeature>          
        </Category>

        <Integer Name="IntegerSignal">
            <Description>Integer Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </Integer>
        <NotASignal Name="NotASignal">
            <Description>Not A Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </NotASignal>
        <IntReg Name="IntRegSignal">
            <Description>IntReg Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </IntReg>
        <IntConverter Name="IntConSignal">
            <Description>IntConverter Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </IntConverter>
        <IntSwissKnife Name="IntSwiKnifeSignal">
            <Description>Int Swiss Knife Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </IntSwissKnife>
        <Boolean Name="BooleanSignal">
            <Description>Boolean Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </Boolean>
        <Float Name="FloatSignal">
            <Description>Float Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </Float>
        <Converter Name="ConverterSignal">
            <Description>Converter Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </Converter>
        <SwissKnife Name="SwissKnifeSignal">
            <Description>Swiss Knife Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </SwissKnife>
        <String Name="StringSignal">
            <Description>String Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </String>
        <StringReg Name="StringRegSignal">
            <Description>StringReg Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </StringReg>
        <Command Name="CommandSignal">
            <Description>Command Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </Command>
        <Enumeration Name="EnumerationSignal">
            <Description>Enumeration Signal</Description>
            <ImposedAccessMode>WO</ImposedAccessMode>
        </Enumeration>   
        </Root>
        """

        genicam_model: GenICamModel = GenICamModel(xml)
        pvi_model: PviModel = PviModel(genicam_model, "Camera")
        groups: list[Group] = pvi_model.groups
        acquisitionGroup = next(g for g in groups if g.name == "AcquisitionCategory")
        signal_names = [s.name for s in acquisitionGroup.children]
        assert set(signal_names) == {
            "GCIntegerSignal",
            "GCIntRegSignal",
            "GCIntConSignal",
            "GCIntSwiKnifeSignal",
            "GCBooleanSignal",
            "GCFloatSignal",
            "GCConverterSignal",
            "GCSwissKnifeSignal",
            "GCStringSignal",
            "GCStringRegSignal",
            "GCCommandSignal",
            "GCEnumerationSignal"
        }

    def test_convert_genicam_xml_to_pvi_generates_yaml(self, example_xml: str):
        yaml_text = makePvi.convert_genicam_xml_to_pvi(
            example_xml,
            instance_class="Camera instance class",
            label="Camera test label"
        )
        print(yaml_text)
        # Load YAML to dict
        ym = YAML(typ='safe', pure=True)
        data = ym.load(yaml_text)
        assert isinstance(data, dict)
        # Device label
        assert data["label"] == "Camera test label"

        groups = data["children"]
        assert len(groups) == 2

        group_names = [g["name"] for g in groups if g["type"] == "Group"]
        assert "AcquisitionCategory" in group_names
        assert "ChildCategoryWithLeaf" in group_names

        firstGroup = next(g for g in groups if g["type"] == "Group" and g["name"] == "AcquisitionCategory")

        assert firstGroup["name"] == "AcquisitionCategory"
        # Signals inside group
        signal_names = [s["name"] for s in firstGroup["children"]]
        assert set(signal_names) == {
            "GCExpTimeFeature",
            "GCGainFeature",
            "GCOffsetFeature"}

    def test_convert_genicam_xml_to_pvi_embedded_in_adaravis(self, example_xml: str):
        yaml_text = makePvi.convert_genicam_xml_to_pvi(
            example_xml,
            instance_class="Camera instance class",
            label="Camera instance ID",
            embed_in="ADAravis",
            embedding_file_folder="./python-tests/",
        )
        print(yaml_text)
        # Load YAML to dict
        ym = YAML(typ='safe', pure=True)
        data = ym.load(yaml_text)
        assert isinstance(data, dict)
        # Device label
        assert data["label"] == "ADAravis Camera + Camera instance ID"

        level_1_childen = data["children"]

        # We have the ADAravis and GenICam groupsS
        group_names = [g["name"] for g in level_1_childen if g["type"] == "Group"]
        assert "ADAravis" in group_names
        assert "GenICam" in group_names

        genicam_group = next(g for g in level_1_childen if g["type"] == "Group" and g["name"] == "GenICam")
        assert genicam_group["type"] == "Group"
        assert genicam_group["name"] == "GenICam"
        assert genicam_group["layout"]["type"] == "SubScreen"

        # Check GenICam's children  
        genicam_children = genicam_group["children"]
        assert len(genicam_children) == 2

        group_names = [g["name"] for g in genicam_children if g["type"] == "Group"]
        assert "AcquisitionCategory" in group_names
        assert "ChildCategoryWithLeaf" in group_names

        firstGroup = next(g for g in genicam_children if g["type"] == "Group" and g["name"] == "AcquisitionCategory")

        assert firstGroup["name"] == "AcquisitionCategory"
        # Signals inside group
        signal_names = [s["name"] for s in firstGroup["children"]]
        assert set(signal_names) == {
            "GCExpTimeFeature",
            "GCGainFeature",
            "GCOffsetFeature"}
