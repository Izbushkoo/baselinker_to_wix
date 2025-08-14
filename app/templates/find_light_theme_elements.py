#!/usr/bin/env python3
"""
Script to find light theme elements in HTML templates that need to be converted to dark theme.
This script scans HTML files and identifies CSS classes, inline styles, and Bootstrap classes
that use light colors and need to be updated for dark theme consistency.
"""

import os
import re
from pathlib import Path
from collections import defaultdict

class LightThemeFinder:
    def __init__(self):
        # Light theme patterns to search for
        self.light_patterns = {
            'backgrounds': [
                r'bg-white\b',
                r'bg-light\b', 
                r'bg-info\b',
                r'bg-warning\b',
                r'bg-success\b',
                r'bg-primary\b',
                r'background-color:\s*white\b',
                r'background-color:\s*#fff\b',
                r'background-color:\s*#ffffff\b',
                r'background:\s*white\b',
                r'background:\s*#fff\b',
                r'background:\s*#ffffff\b',
                r'background:\s*linear-gradient\([^)]*white[^)]*\)',
                r'background:\s*linear-gradient\([^)]*#fff[^)]*\)',
            ],
            'text_colors': [
                r'text-dark\b',
                r'text-black\b',
                r'text-muted\b',
                r'color:\s*black\b',
                r'color:\s*#000\b',
                r'color:\s*#000000\b',
                r'color:\s*#333\b',
                r'color:\s*#666\b',
                r'color:\s*#999\b',
                r'color:\s*rgb\(0,\s*0,\s*0\)',
            ],
            'borders': [
                r'border-light\b',
                r'border:\s*1px\s+solid\s+#[def][def][def]\b',
                r'border-color:\s*#[def][def][def]\b',
                r'border-top:\s*1px\s+solid\s+#[def][def][def]\b',
                r'border-bottom:\s*1px\s+solid\s+#[def][def][def]\b',
            ],
            'cards_and_containers': [
                r'card\b(?!\s*-\s*(dark|bg-dark))',
                r'table-light\b',
                r'list-group-item\b(?!\s*-\s*dark)',
                r'navbar-light\b',
                r'alert-light\b',
                r'badge-light\b',
            ],
            'buttons': [
                r'btn-light\b',
                r'btn-outline-dark\b',
                r'btn-secondary\b(?!\s*-\s*dark)',
            ]
        }
        
        # Dark theme replacements
        self.dark_replacements = {
            'bg-white': 'bg-dark',
            'bg-light': 'bg-dark', 
            'bg-info': 'bg-info',  # Keep info but check if needs darkening
            'text-dark': 'text-light',
            'text-black': 'text-white',
            'text-muted': 'text-light',
            'border-light': 'border-secondary',
            'btn-light': 'btn-dark',
            'btn-outline-dark': 'btn-outline-light',
            'card': 'card bg-dark text-light',
            'table-light': 'table-dark',
            'navbar-light': 'navbar-dark',
            'alert-light': 'alert-dark',
            'badge-light': 'badge-dark',
        }

    def scan_file(self, file_path):
        """Scan a single HTML file for light theme elements."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return {}
            
        findings = defaultdict(list)
        
        # Split content into lines for line number reporting
        lines = content.split('\n')
        
        for category, patterns in self.light_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    # Find line number
                    line_num = content[:match.start()].count('\n') + 1
                    line_content = lines[line_num - 1].strip()
                    
                    findings[category].append({
                        'line': line_num,
                        'match': match.group(),
                        'context': line_content,
                        'position': match.span()
                    })
        
        return findings

    def scan_directory(self, directory_path):
        """Scan all HTML files in a directory."""
        directory = Path(directory_path)
        results = {}
        
        # Find all HTML files
        html_files = list(directory.glob('*.html'))
        
        if not html_files:
            print(f"No HTML files found in {directory_path}")
            return results
            
        print(f"Scanning {len(html_files)} HTML files in {directory_path}")
        
        for html_file in html_files:
            findings = self.scan_file(html_file)
            if any(findings.values()):  # Only include files with findings
                results[str(html_file)] = findings
                
        return results

    def generate_report(self, results):
        """Generate a detailed report of findings."""
        if not results:
            print("✅ No light theme elements found!")
            return
            
        print("\n" + "="*80)
        print("🔍 LIGHT THEME ELEMENTS FOUND")
        print("="*80)
        
        total_issues = 0
        
        for file_path, findings in results.items():
            file_issues = sum(len(items) for items in findings.values())
            total_issues += file_issues
            
            print(f"\n📄 {Path(file_path).name}")
            print(f"   Issues found: {file_issues}")
            print("-" * 60)
            
            for category, items in findings.items():
                if items:
                    print(f"\n  📋 {category.upper().replace('_', ' ')} ({len(items)} issues):")
                    for item in items:
                        print(f"    Line {item['line']:3d}: {item['match']}")
                        if len(item['context']) > 80:
                            context = item['context'][:80] + "..."
                        else:
                            context = item['context']
                        print(f"               {context}")
        
        print("\n" + "="*80)
        print(f"📊 SUMMARY: {total_issues} light theme elements found across {len(results)} files")
        print("="*80)

    def suggest_replacements(self, results):
        """Suggest specific replacements for found elements."""
        if not results:
            return
            
        print("\n" + "="*80)
        print("💡 SUGGESTED REPLACEMENTS")
        print("="*80)
        
        for file_path, findings in results.items():
            print(f"\n📄 {Path(file_path).name}")
            print("-" * 60)
            
            for category, items in findings.items():
                if items:
                    print(f"\n  {category.upper().replace('_', ' ')}:")
                    for item in items:
                        match = item['match']
                        suggestion = self.get_replacement_suggestion(match)
                        print(f"    Line {item['line']}: '{match}' → '{suggestion}'")

    def get_replacement_suggestion(self, match):
        """Get replacement suggestion for a specific match."""
        # Direct replacements
        for old, new in self.dark_replacements.items():
            if old in match:
                return match.replace(old, new)
        
        # Pattern-based replacements
        if 'background-color:' in match and ('white' in match or '#fff' in match):
            return re.sub(r'(background-color:\s*)(white|#fff(?:fff)?)', r'\1#333', match)
        elif 'color:' in match and ('#000' in match or 'black' in match):
            return re.sub(r'(color:\s*)(black|#000(?:000)?)', r'\1white', match)
        elif 'border:' in match and re.search(r'#[def][def][def]', match):
            return re.sub(r'#[def][def][def]', '#555', match)
            
        return f"{match} → (needs manual review)"

def main():
    finder = LightThemeFinder()
    
    # Scan current directory for HTML templates
    current_dir = os.getcwd()
    print(f"🔍 Scanning HTML templates in: {current_dir}")
    
    results = finder.scan_directory(current_dir)
    finder.generate_report(results)
    finder.suggest_replacements(results)
    
    if results:
        print(f"\n💾 Results can be used to systematically update templates to dark theme.")
        print("🚀 Next steps:")
        print("   1. Review the suggested replacements")
        print("   2. Create backup of templates before making changes")
        print("   3. Apply changes file by file")
        print("   4. Test each template after changes")

if __name__ == "__main__":
    main()
