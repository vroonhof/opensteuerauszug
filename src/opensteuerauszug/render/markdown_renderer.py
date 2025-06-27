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

        new_root = Element("div")
        in_section = False
        for element in root:
            # The attr_list extension adds attributes to the element
            css_class = element.get('class', '')
            
            if self.section in css_class:
                # This is the start of a section we want to extract
                in_section = True
                # We don't include the section marker itself, just the content after it
                continue

            if in_section:
                # If we encounter another section marker, we stop
                if 'short-version' in css_class or 'long-version' in css_class:
                    in_section = False
                    continue
                new_root.append(element)
        
        # If we are still in a section at the end, it means the section
        # continued to the end of the document
        if in_section:
             # To be safe, we clear the original root and append the children
             # of our new_root
            root.clear()
            for child in new_root:
                root.append(child)
        
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