import sys
from pathlib import Path

# Allow importing MakePvi.py from ioc/scripts
SCRIPT_DIR = Path(__file__).resolve().parents[1] / "ioc" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import makePvi

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

