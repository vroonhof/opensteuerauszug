from markdown import Markdown
from markdown.treeprocessors import Treeprocessor
from markdown.extensions import Extension
from reportlab.platypus import Paragraph, Spacer, ListFlowable, ListItem
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from xml.etree.ElementTree import Element, SubElement

def _etree_to_string(element: Element) -> str:
    """Recursively converts an ElementTree element to a string with ReportLab XML tags."""
    text = element.text or ""
    
    tag_map = {
        'strong': 'b',
        'em': 'i',
        'code': 'font name="Courier"',
    }
    
    for child in element:
        if child.tag in tag_map:
            open_tag = f"<{tag_map[child.tag]}>"
            close_tag = f"</{tag_map[child.tag].split()[0]}>"
        else:
            open_tag = ""
            close_tag = ""
            
        text += open_tag + _etree_to_string(child) + close_tag
        
        if child.tail:
            text += child.tail
            
    return text.strip()

class SectionExtractorTreeprocessor(Treeprocessor):
    def __init__(self, md, section=None):
        super().__init__(md)
        self.section = section

    def run(self, root: Element):
        if not self.section:
            return root

        section_content = []
        
        # The marker is a paragraph with the literal text like "{: .short-version }".
        start_marker = f"{{: .{self.section} }}"
        
        start_marker_index = -1
        for i, element in enumerate(root):
            if element.tag == 'p' and element.text and element.text.strip() == start_marker:
                start_marker_index = i
                break
        
        if start_marker_index != -1:
            # Content starts from the element *after* the marker.
            content_start_index = start_marker_index + 1
            
            # Find the end of the section, which is the next marker or end of doc.
            end_marker_index = len(root)
            for i in range(content_start_index, len(root)):
                element = root[i]
                if element.tag == 'p' and element.text and (
                    element.text.strip() == "{: .short-version }" or
                    element.text.strip() == "{: .long-version }"
                ):
                    end_marker_index = i
                    break
            section_content = root[content_start_index:end_marker_index]

        # Preserve title if it exists
        title = []
        if len(root) > 0 and root[0].tag.startswith('h'):
            title.append(root[0])
            
        # Replace the original root with the new one
        root.clear()
        root.extend(title)
        root.extend(section_content)
            
        return root


class PlatypusTreeprocessor(Treeprocessor):
    def __init__(self, md):
        super().__init__(md)
        self.flowables = []
        self.styles = getSampleStyleSheet()

    def run(self, root: Element):
        self.flowables = []
        # Always add the title
        if len(root) > 0 and root[0].tag.startswith('h'):
            title_element = root[0]
            level = int(title_element.tag[1])
            style_name = f'h{level}'
            text = _etree_to_string(title_element)
            self.flowables.append(Paragraph(text, self.styles[style_name]))
            self.flowables.append(Spacer(1, 0.2 * cm))

        for element in root[1:]: # Skip the title
            if element.tag.startswith('h'):
                level = int(element.tag[1])
                style_name = f'h{level}'
                text = _etree_to_string(element)
                self.flowables.append(Paragraph(text, self.styles[style_name]))
                self.flowables.append(Spacer(1, 0.2 * cm))

            elif element.tag == 'p':
                text = _etree_to_string(element)
                if text:
                    self.flowables.append(Paragraph(text, self.styles['BodyText']))
                    self.flowables.append(Spacer(1, 0.2 * cm))

            elif element.tag in ['ul', 'ol']:
                items = []
                for li in element:
                    text = _etree_to_string(li)
                    items.append(ListItem(Paragraph(text, self.styles['BodyText'])))
                
                list_flowable = ListFlowable(
                    items,
                    bulletType='1' if element.tag == 'ol' else 'bullet',
                    start='1' if element.tag == 'ol' else None,
                )
                self.flowables.append(list_flowable)
                self.flowables.append(Spacer(1, 0.2 * cm))

        return root


class PlatypusExtension(Extension):
    def __init__(self, *args, **kwargs):
        self.section = kwargs.pop('section', None)
        super().__init__(*args, **kwargs)

    def extendMarkdown(self, md):
        md.treeprocessors.register(SectionExtractorTreeprocessor(md, self.section), 'section_extractor', 6)
        md.treeprocessors.register(PlatypusTreeprocessor(md), 'platypus', 5)


def markdown_to_platypus(markdown_text: str, section: str = None):
    """
    Converts a Markdown string to a list of ReportLab Platypus Flowables.
    """
    platypus_ext = PlatypusExtension(section=section)
    md = Markdown(extensions=['attr_list', platypus_ext], output_format="html")
    md.convert(markdown_text)
    
    processor = md.treeprocessors['platypus']
    return processor.flowables
