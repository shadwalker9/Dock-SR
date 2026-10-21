"""Navigation, source boundaries and completeness of original research summaries."""
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / 'docs/research'


def anchors(text):
    result = set()
    for line in text.splitlines():
        if not line.startswith('#'): continue
        title = line.lstrip('#').strip().lower()
        result.add(re.sub(r'[^\w -]', '', title).replace(' ', '-'))
    return result


class ResearchHubTests(unittest.TestCase):
    def test_links_and_readme_navigation(self):
        paths = [ROOT / 'README.md', *HUB.glob('*.md')]
        self.assertIn('docs/research/README.md', paths[0].read_text().split('## Mission')[0])
        for path in paths:
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                if '://' in target: continue
                filename, _, fragment = target.partition('#')
                destination = path.parent / filename if filename else path
                with self.subTest(path=path.name, target=target):
                    self.assertTrue(destination.is_file())
                    if fragment:
                        self.assertIn(fragment, anchors(destination.read_text()))

    def test_research_and_decision_ids(self):
        page = (HUB / 'README.md').read_text()
        self.assertEqual(set(re.findall(r'R-00[5-9]', page)), {f'R-{i:03}' for i in range(5, 10)})
        self.assertIn('original document was unavailable', page)
        consensus = (HUB / 'CONSENSUS.md').read_text()
        self.assertEqual(re.findall(r'^## (C-\d{3})', consensus, re.M), [f'C-{i:03}' for i in range(1, 13)])
        self.assertEqual(consensus.count('Hardware validation: NOT_TESTED.'), 12)
        for section in re.split(r'^## C-\d{3}', consensus, flags=re.M)[1:]:
            for field in ('Source:', 'Decision/reason:', 'Confidence:', 'Revisit:', 'Implementation:', 'Hardware validation:'):
                self.assertIn(field, section)

    def test_private_data_and_artifact_boundaries(self):
        for path in HUB.rglob('*'):
            if not path.is_file(): continue
            self.assertEqual(path.suffix, '.md')
            text = path.read_text()
            for forbidden in ('/workspace/', '/home/', '/tmp/', 'sediment://', 'PRIVATE PROGRESS REPORT', 'ghp_', 'github_pat_'):
                with self.subTest(path=path.name, forbidden=forbidden): self.assertNotIn(forbidden, text)
        self.assertIn('Formal DockSR licensing remains pending', (HUB / 'SOURCES.md').read_text())

    def test_unknowns_and_source_register(self):
        text = (HUB / 'README.md').read_text()
        unknowns = text.split('## What We Have Not Proven Yet')[1].split('## How to Continue')[0]
        self.assertEqual(len(re.findall(r'^- No ', unknowns, re.M)), 9)
        sources = (HUB / 'SOURCES.md').read_text()
        self.assertEqual(re.findall(r'^\| (S-\d{3})', sources, re.M), [f'S-{i:03}' for i in range(1, 11)])
        self.assertIn('SteamOS is the primary', text)


if __name__ == '__main__':
    unittest.main()
