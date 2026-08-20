# -*- coding: utf-8 -*-
"""Önizleme rasterleştirmesi için CSS inline etme davranışı."""

import unittest
import xml.etree.ElementTree as ET

import etki_analizi_izlenebilirlik as traceability
import mimari_cerceve_cikarim as extraction
import mimari_cerceve_render as rendering
import mimari_cerceve_yonetim as management

SVG_NS = rendering.SVG_NS

# Önizleme testleri kendi küçük mimarisini kurar; başka modüle bağlı değildir.
_FLAT = {
    "STT-001": {
        "type": "STT", "ID": "STT-001", "bound_to": "Yok",
        "content": (
            "Radar Sensör Birimi, hedef tespit verisini Görev Kontrol "
            "Sistemi'ne Ethernet arayüzü üzerinden iletmelidir"
        ),
    },
    "STT-002": {
        "type": "STT", "ID": "STT-002", "bound_to": "Yok",
        "content": (
            "Görev Kontrol Sistemi, alarm mesajını Operatör Konsolu "
            "Ünitesi'ne Ethernet arayüzü üzerinden iletmelidir"
        ),
    },
}


def _example_svg(profile_id="dodaf", view_id="SV-1"):
    report = traceability.build_traceability_map(
        "Önizleme Testi", flat_data=_FLAT, persist=False, check_lm_studio=False,
    )
    result = extraction.extract_architecture_candidates(
        _FLAT, report, framework_profile_id=profile_id,
    )
    state = management.create_management_state(
        "Önizleme Testi", result.candidates, framework_profile_id=profile_id,
    )
    ordered = sorted(state.records, key=lambda record_id: (
        state.records[record_id].proposal.proposal_type != "element", record_id,
    ))
    for record_id in ordered:
        management.approve_candidate(state, record_id, "test")
    snapshot = management.build_working_snapshot(
        state, (view_id,), version="v0001",
    )
    return rendering.render_view(snapshot, view_id).svg


class StyleRuleParsingTests(unittest.TestCase):

    def test_class_selector_declarations_are_collected(self):
        rules = rendering.parse_style_rules(".node-name { fill: #172b3a; }")
        self.assertEqual(rules[".node-name"]["fill"], "#172b3a")

    def test_font_shorthand_is_expanded_into_separate_attributes(self):
        rules = rendering.parse_style_rules(
            ".title { font: 700 24px 'Segoe UI', Arial, sans-serif; fill: #182230; }"
        )
        title = rules[".title"]
        self.assertEqual(title["font-weight"], "700")
        self.assertEqual(title["font-size"], "24")
        self.assertIn("Segoe UI", title["font-family"])

    def test_descendant_selector_is_kept_separate(self):
        rules = rendering.parse_style_rules(".node rect { fill: #ffffff; }")
        self.assertIn(".node rect", rules)

    def test_non_presentation_properties_are_ignored(self):
        rules = rendering.parse_style_rules(".x { text-decoration: underline; }")
        self.assertNotIn(".x", rules)


class InlineStyleTests(unittest.TestCase):

    def test_background_class_receives_its_fill_attribute(self):
        svg = _example_svg()
        inlined = rendering.svg_with_inline_styles(svg)
        root = ET.fromstring(inlined)
        backgrounds = [
            node for node in root.iter()
            if "background" in (node.get("class") or "")
        ]
        self.assertTrue(backgrounds)
        self.assertTrue(all(node.get("fill") for node in backgrounds))

    def test_descendant_rule_reaches_nested_rect(self):
        svg = _example_svg()
        inlined = rendering.svg_with_inline_styles(svg)
        root = ET.fromstring(inlined)
        filled = [
            child for node in root.iter()
            if "node" in (node.get("class") or "").split()
            for child in node.iter(f"{{{SVG_NS}}}rect")
            if child.get("fill")
        ]
        self.assertTrue(filled, "iç içe rect fill özniteliği almadı")

    def test_input_svg_is_not_modified(self):
        svg = _example_svg()
        original = str(svg)
        rendering.svg_with_inline_styles(svg)
        self.assertEqual(svg, original)

    def test_svg_without_style_block_is_returned_unchanged(self):
        plain = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
        self.assertIs(rendering.svg_with_inline_styles(plain), plain)

    def test_unparsable_svg_is_returned_unchanged(self):
        broken = '<svg><style>.a{fill:#fff;}</style><rect>'
        self.assertIs(rendering.svg_with_inline_styles(broken), broken)

    def test_result_stays_valid_xml_with_svg_namespace(self):
        inlined = rendering.svg_with_inline_styles(_example_svg())
        root = ET.fromstring(inlined)
        self.assertTrue(root.tag.endswith("svg"))


class PreviewRasterTests(unittest.TestCase):
    """Siyah önizleme regresyonu: rasterleştirilen görüntü boş olmamalıdır."""

    def _average_luminance(self, svg):
        from mimari_cerceve_ui import ArchitectureFrameworkWorkspace

        image = ArchitectureFrameworkWorkspace._rasterize_svg_preview(svg, (600, 400))
        grey = image.convert("L")
        pixels = list(grey.getdata())
        return sum(pixels) / len(pixels)

    def test_rendered_preview_is_not_a_black_rectangle(self):
        average = self._average_luminance(_example_svg())
        self.assertGreater(
            average, 100,
            f"önizleme karartılmış görünüyor (ortalama parlaklık {average:.1f})",
        )

    def test_naf_preview_is_also_visible(self):
        average = self._average_luminance(_example_svg("naf", "L3"))
        self.assertGreater(average, 100)


if __name__ == "__main__":
    unittest.main()
