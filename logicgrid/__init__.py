"""Dynamic logic-grid puzzle generator."""

from .generate import Puzzle, generate_puzzle
from .model import Category, Theme
from .render import render_puzzle
from .solver import count_solutions, is_unique
from .themes import load_theme, theme_from_dict

__all__ = [
    "Puzzle",
    "generate_puzzle",
    "Category",
    "Theme",
    "render_puzzle",
    "count_solutions",
    "is_unique",
    "load_theme",
    "theme_from_dict",
]
