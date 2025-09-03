# tests/render/test_markdown_renderer.py
import unittest
from src.opensteuerauszug.render.markdown_renderer import markdown_to_platypus
from reportlab.platypus import Paragraph, Spacer

class TestMarkdownSectionExtractor(unittest.TestCase):

    def test_no_section_filtering(self):
        """
        Tests that if no section is specified, the entire Markdown content is processed.
        """
        markdown_text = """
# Document Title

Some introductory text.

{: .short-version }
## Short Section

Content of the short section.

{: .long-version }
## Long Section

Content of the long section.
"""
        flowables = markdown_to_platypus(markdown_text)
        text_content = " ".join([f.text for f in flowables if hasattr(f, 'text')])

        self.assertIn("Document Title", text_content)
        self.assertIn("Some introductory text", text_content)
        self.assertIn("Short Section", text_content)
        self.assertIn("Content of the short section", text_content)
        self.assertIn("Long Section", text_content)
        self.assertIn("Content of the long section", text_content)

    def test_extract_short_version_section(self):
        """
        Tests that only the 'short-version' section is extracted when specified.
        """
        markdown_text = """
# Document Title

Some introductory text.

{: .short-version }
## Short Section

Content of the short section.

{: .long-version }
## Long Section

Content of the long section.
"""
        flowables = markdown_to_platypus(markdown_text, section='short-version')
        text_content = " ".join([f.text for f in flowables if hasattr(f, 'text')])

        self.assertIn("Document Title", text_content)
        self.assertNotIn("Some introductory text", text_content)
        self.assertIn("Short Section", text_content)
        self.assertIn("Content of the short section", text_content)
        self.assertNotIn("Long Section", text_content)
        self.assertNotIn("Content of the long section", text_content)

    def test_extract_long_version_section(self):
        """
        Tests that only the 'long-version' section is extracted when specified.
        """
        markdown_text = """
# Document Title

Some introductory text.

{: .short-version }
## Short Section

Content of the short section.

{: .long-version }
## Long Section

Content of the long section.
"""
        flowables = markdown_to_platypus(markdown_text, section='long-version')
        text_content = " ".join([f.text for f in flowables if hasattr(f, 'text')])

        self.assertIn("Document Title", text_content)
        self.assertNotIn("Some introductory text", text_content)
        self.assertNotIn("Short Section", text_content)
        self.assertNotIn("Content of the short section", text_content)
        self.assertIn("Long Section", text_content)
        self.assertIn("Content of the long section", text_content)

    def test_section_extends_to_end_of_document(self):
        """
        Tests extraction of a section that is the last part of the document.
        """
        markdown_text = """
# Document Title

Some introductory text.

{: .short-version }
## Short Section

Content of the short section that continues to the end.
"""
        flowables = markdown_to_platypus(markdown_text, section='short-version')
        text_content = " ".join([f.text for f in flowables if hasattr(f, 'text')])

        self.assertIn("Document Title", text_content)
        self.assertNotIn("Some introductory text", text_content)
        self.assertIn("Short Section", text_content)
        self.assertIn("Content of the short section that continues to the end.", text_content)

    def test_nonexistent_section(self):
        """
        Tests that if a non-existent section is requested, only the title is returned.
        """
        markdown_text = """
# Document Title

{: .short-version }
## Short Section

Content of the short section.
"""
        flowables = markdown_to_platypus(markdown_text, section='nonexistent-section')
        text_content = " ".join([f.text for f in flowables if hasattr(f, 'text')])

        self.assertIn("Document Title", text_content)
        self.assertNotIn("Short Section", text_content)
        self.assertNotIn("Content of the short section", text_content)
        
        # Expect only title and a spacer
        self.assertEqual(len(flowables), 2)
        self.assertIsInstance(flowables[0], Paragraph)
        self.assertEqual(flowables[0].text, "Document Title")
        self.assertIsInstance(flowables[1], Spacer)

    def test_empty_markdown(self):
        """
        Tests that empty markdown input doesn't cause errors.
        """
        flowables = markdown_to_platypus("", section='short-version')
        self.assertEqual(len(flowables), 0)

    def test_markdown_with_no_sections(self):
        """
        Tests that if a section is requested from markdown with no section markers,
        only the title is returned.
        """
        markdown_text = """
# Document Title

Some text without any sections.
"""
        flowables = markdown_to_platypus(markdown_text, section='short-version')
        text_content = " ".join([f.text for f in flowables if hasattr(f, 'text')])
        self.assertIn("Document Title", text_content)
        self.assertNotIn("Some text without any sections", text_content)
