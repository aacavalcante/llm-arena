#!/usr/bin/env python3
"""Roda as soluções de referência do banco de desafios no sandbox. Uso: uv run scripts/verify_challenges.py [bank]"""

import sys

from llmarena.challenges.verify import main

sys.exit(main(*sys.argv[1:]))
