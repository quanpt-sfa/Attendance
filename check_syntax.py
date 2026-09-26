#!/usr/bin/env python3
"""Quick JS syntax check for HTML files"""
import re, sys

for fname in ['index.html', 'scan.html']:
    content = open(fname, encoding='utf-8').read()
    scripts = re.findall(r'<script>(.*?)</script>', content, re.DOTALL)
    for i, script in enumerate(scripts):
        braces = parens = brackets = 0
        in_str = None
        prev = ''
        for ch in script:
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
        status = 'OK' if braces == 0 and parens == 0 and brackets == 0 else 'MISMATCH!'
        print(f'{fname} script#{i}: {{{braces}}} ({parens}) [{brackets}] => {status}')
