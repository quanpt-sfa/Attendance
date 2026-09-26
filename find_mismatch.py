#!/usr/bin/env python3
"""Find JS brace/paren mismatch locations in HTML files"""
import re

for fname in ['index.html', 'scan.html']:
    content = open(fname, encoding='utf-8').read()
    lines = content.split('\n')
    
    # Find script start line 
    script_match = re.search(r'<script>', content)
    if not script_match:
        continue
    script_start_line = content[:script_match.end()].count('\n') + 1
    
    scripts = re.findall(r'<script>(.*?)</script>', content, re.DOTALL)
    if not scripts:
        continue
    
    script = scripts[0]
    script_lines = script.split('\n')
    
    print(f'\n=== {fname} (script starts at line {script_start_line}) ===')
    
    # Track running counts per line
    braces = parens = brackets = 0
    in_str = None
    prev = ''
    
    for line_idx, line in enumerate(script_lines):
        old_b, old_p, old_br = braces, parens, brackets
        for ch in line:
            if in_str:
                if ch == in_str and prev != '\\':
                    in_str = None
            elif ch in ('"', "'", '`'):
                in_str = ch
            elif ch == '{': braces += 1
            elif ch == '}': braces -= 1
            elif ch == '(': parens += 1
            elif ch == ')': parens -= 1
            elif ch == '[': brackets += 1
            elif ch == ']': brackets -= 1
            prev = ch
        
        actual_line = script_start_line + line_idx
        db = braces - old_b
        dp = parens - old_p
        dbr = brackets - old_br
        
        # Only print lines that change balance OR where balance goes negative
        if braces < 0 or parens < 0 or brackets < 0:
            print(f'  LINE {actual_line}: NEGATIVE! {{{braces}}} ({parens}) [{brackets}] | {line.strip()[:80]}')
        
        # Print when balance returns to unusual levels
        if abs(db) > 1 or abs(dp) > 1 or abs(dbr) > 1:
            print(f'  LINE {actual_line}: big change d{{{db}}} d({dp}) d[{dbr}] => {{{braces}}} ({parens}) [{brackets}] | {line.strip()[:80]}')
    
    print(f'  FINAL: {{{braces}}} ({parens}) [{brackets}]')
    
    if in_str:
        print(f'  WARNING: unterminated string (delimiter: {in_str})')
