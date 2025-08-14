#!/usr/bin/env python3
"""
Script to automatically apply dark theme changes to HTML templates.
This script uses the findings from find_light_theme_elements.py to systematically
convert light theme elements to dark theme equivalents.
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime

class DarkThemeApplier:
    def __init__(self):
        # Comprehensive mapping of light to dark theme replacements
        self.replacements = {
            # Bootstrap background classes
            'bg-white': 'bg-dark',
            'bg-light': 'bg-dark',
            
            # Bootstrap text classes
            'text-dark': 'text-light',
            'text-black': 'text-white',
            'text-muted': 'text-light',
            
            # Bootstrap border classes
            'border-light': 'border-secondary',
            
            # Bootstrap button classes
            'btn-light': 'btn-dark',
            'btn-outline-dark': 'btn-outline-light',
            
            # Bootstrap component classes
            'table-light': 'table-dark',
            'navbar-light': 'navbar-dark bg-dark',
            'alert-light': 'alert-dark',
            'badge-light': 'badge-dark',
            'list-group-item': 'list-group-item list-group-item-dark bg-dark text-light',
            
            # Card classes - need special handling
            'class="card"': 'class="card bg-dark text-light"',
            'class="card ': 'class="card bg-dark text-light ',
            
            # Form classes
            'form-control': 'form-control bg-dark text-light border-secondary',
            'form-select': 'form-select bg-dark text-light border-secondary',
        }
        
        # CSS style replacements (regex patterns)
        self.css_patterns = [
            # Background colors
            (r'background-color:\s*white\b', 'background-color: #333'),
            (r'background-color:\s*#fff\b', 'background-color: #333'),
            (r'background-color:\s*#ffffff\b', 'background-color: #333'),
            (r'background:\s*white\b', 'background: #333'),
            (r'background:\s*#fff\b', 'background: #333'),
            (r'background:\s*#ffffff\b', 'background: #333'),
            
            # Text colors
            (r'color:\s*black\b', 'color: white'),
            (r'color:\s*#000\b', 'color: white'),
            (r'color:\s*#000000\b', 'color: white'),
            (r'color:\s*#333\b', 'color: #ccc'),
            (r'color:\s*#666\b', 'color: #aaa'),
            (r'color:\s*#999\b', 'color: #888'),
            
            # Border colors
            (r'border:\s*1px\s+solid\s+#[def][def][def]', 'border: 1px solid #555'),
            (r'border-color:\s*#[def][def][def]', 'border-color: #555'),
            (r'border-top:\s*1px\s+solid\s+#[def][def][def]', 'border-top: 1px solid #555'),
            (r'border-bottom:\s*1px\s+solid\s+#[def][def][def]', 'border-bottom: 1px solid #555'),
            
            # Linear gradients with light colors
            (r'background:\s*linear-gradient\([^)]*white[^)]*\)', 'background: linear-gradient(to bottom, #444, #333)'),
            (r'background:\s*linear-gradient\([^)]*#fff[^)]*\)', 'background: linear-gradient(to bottom, #444, #333)'),
        ]

    def create_backup(self, file_path):
        """Create a backup of the original file."""
        backup_path = f"{file_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(file_path, backup_path)
        return backup_path

    def apply_class_replacements(self, content):
        """Apply Bootstrap class replacements."""
        modified_content = content
        changes_made = []
        
        for old_class, new_class in self.replacements.items():
            if old_class in modified_content:
                modified_content = modified_content.replace(old_class, new_class)
                changes_made.append(f"{old_class} → {new_class}")
        
        return modified_content, changes_made

    def apply_css_replacements(self, content):
        """Apply CSS style replacements using regex patterns."""
        modified_content = content
        changes_made = []
        
        for pattern, replacement in self.css_patterns:
            matches = re.findall(pattern, modified_content, re.IGNORECASE)
            if matches:
                modified_content = re.sub(pattern, replacement, modified_content, flags=re.IGNORECASE)
                changes_made.extend([f"{match} → {replacement}" for match in matches])
        
        return modified_content, changes_made

    def fix_card_classes(self, content):
        """Special handling for card classes that need more context."""
        modified_content = content
        changes_made = []
        
        # Find card elements that don't already have dark theme classes
        card_pattern = r'class="([^"]*\bcard\b[^"]*)"'
        matches = re.finditer(card_pattern, modified_content)
        
        for match in matches:
            full_class = match.group(1)
            if 'bg-dark' not in full_class and 'text-light' not in full_class:
                # Add dark theme classes
                new_class = full_class + ' bg-dark text-light'
                modified_content = modified_content.replace(f'class="{full_class}"', f'class="{new_class}"')
                changes_made.append(f'card class enhanced: "{full_class}" → "{new_class}"')
        
        return modified_content, changes_made

    def fix_input_fields(self, content):
        """Fix input fields and form controls for dark theme."""
        modified_content = content
        changes_made = []
        
        # Form controls
        form_patterns = [
            (r'class="([^"]*\bform-control\b[^"]*)"', 'form-control bg-dark text-light border-secondary'),
            (r'class="([^"]*\bform-select\b[^"]*)"', 'form-select bg-dark text-light border-secondary'),
        ]
        
        for pattern, replacement_classes in form_patterns:
            matches = re.finditer(pattern, modified_content)
            for match in matches:
                full_class = match.group(1)
                if 'bg-dark' not in full_class:
                    # Replace the form control class with dark theme version
                    new_class = re.sub(r'\bform-(control|select)\b', replacement_classes, full_class)
                    modified_content = modified_content.replace(f'class="{full_class}"', f'class="{new_class}"')
                    changes_made.append(f'form field updated: "{full_class}" → "{new_class}"')
        
        return modified_content, changes_made

    def apply_dark_theme(self, file_path, dry_run=False):
        """Apply dark theme changes to a single file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
        except Exception as e:
            return False, f"Error reading {file_path}: {e}", []

        # Apply all transformations
        content = original_content
        all_changes = []
        
        # 1. Apply class replacements
        content, changes = self.apply_class_replacements(content)
        all_changes.extend(changes)
        
        # 2. Apply CSS style replacements
        content, changes = self.apply_css_replacements(content)
        all_changes.extend(changes)
        
        # 3. Fix card classes
        content, changes = self.fix_card_classes(content)
        all_changes.extend(changes)
        
        # 4. Fix input fields
        content, changes = self.fix_input_fields(content)
        all_changes.extend(changes)
        
        # Check if any changes were made
        if content == original_content:
            return True, "No changes needed", []
        
        if not dry_run:
            # Create backup
            backup_path = self.create_backup(file_path)
            
            # Write modified content
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True, f"Successfully updated (backup: {backup_path})", all_changes
            except Exception as e:
                return False, f"Error writing {file_path}: {e}", []
        else:
            return True, "Dry run - changes would be applied", all_changes

    def process_directory(self, directory_path, dry_run=True, exclude_files=None):
        """Process all HTML files in a directory."""
        if exclude_files is None:
            exclude_files = ['allegro_orders.html', 'synchronization.html']  # Already converted
        
        directory = Path(directory_path)
        html_files = list(directory.glob('*.html'))
        
        # Filter out excluded files
        html_files = [f for f in html_files if f.name not in exclude_files]
        
        if not html_files:
            print(f"No HTML files to process in {directory_path}")
            return {}
        
        results = {}
        print(f"{'🔍 DRY RUN: ' if dry_run else '🚀 APPLYING: '}Processing {len(html_files)} HTML files...")
        
        for html_file in html_files:
            success, message, changes = self.apply_dark_theme(html_file, dry_run)
            results[str(html_file)] = {
                'success': success,
                'message': message,
                'changes': changes
            }
            
            # Print progress
            status = "✅" if success else "❌"
            change_count = len(changes)
            print(f"{status} {html_file.name}: {message} ({change_count} changes)")
            
            # Show first few changes as preview
            if changes and len(changes) > 0:
                preview_count = min(3, len(changes))
                for i in range(preview_count):
                    print(f"    - {changes[i]}")
                if len(changes) > preview_count:
                    print(f"    ... and {len(changes) - preview_count} more changes")
        
        return results

def main():
    applier = DarkThemeApplier()
    current_dir = os.getcwd()
    
    print("🎨 Dark Theme Auto-Applier")
    print("=" * 50)
    print(f"Working directory: {current_dir}")
    
    # First, run a dry run to show what would be changed
    print("\n🔍 PHASE 1: DRY RUN (Preview changes)")
    print("-" * 50)
    dry_results = applier.process_directory(current_dir, dry_run=True)
    
    if not dry_results:
        print("No files to process.")
        return
    
    # Show summary
    total_changes = sum(len(result['changes']) for result in dry_results.values())
    files_with_changes = sum(1 for result in dry_results.values() if result['changes'])
    
    print(f"\n📊 DRY RUN SUMMARY:")
    print(f"Files that would be modified: {files_with_changes}")
    print(f"Total changes that would be applied: {total_changes}")
    
    if total_changes == 0:
        print("✅ All files are already using dark theme!")
        return
    
    # Ask for confirmation
    print(f"\n🚀 PHASE 2: Apply changes?")
    print("This will:")
    print("- Create backup files for each modified template")
    print("- Apply dark theme changes to all templates")
    print("- Show detailed results")
    
    response = input("\nProceed with applying changes? (y/N): ").strip().lower()
    
    if response in ['y', 'yes']:
        print("\n🚀 APPLYING CHANGES...")
        print("-" * 50)
        results = applier.process_directory(current_dir, dry_run=False)
        
        # Final summary
        successful = sum(1 for result in results.values() if result['success'])
        failed = len(results) - successful
        
        print(f"\n🎉 FINAL RESULTS:")
        print(f"Successfully modified: {successful} files")
        print(f"Failed: {failed} files")
        
        if failed > 0:
            print(f"\n❌ Failed files:")
            for file_path, result in results.items():
                if not result['success']:
                    print(f"  - {Path(file_path).name}: {result['message']}")
        
        print(f"\n✅ Dark theme conversion complete!")
        print(f"💡 Tip: Test your templates to ensure everything looks correct.")
        print(f"💡 Backup files were created in case you need to revert changes.")
    else:
        print("Operation cancelled.")

if __name__ == "__main__":
    main()
