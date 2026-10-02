"""Shared player-facing controls for the game menu and local help overlay."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_CONTROLS = {'title': 'HOW TO PLAY',
 'subtitle': 'Take your time. The road waits for your choice.',
 'sections': [{'heading': 'Read and choose',
               'text': 'Space or Enter reveals the current page, then continues the story. '
                       'Backspace revisits the previous page. Tab opens or closes the story '
                       'transcript. Use the arrow keys and Enter to choose, press a number '
                       'from 1 to 9, or click an answer. In the transcript, Ctrl+F or '
                       'Command+F searches the full record. Enter and Shift+Enter move '
                       'between matches; F3 repeats the saved search. Escape first leaves '
                       'search, then closes the transcript.'},
              {'heading': 'Explore',
               'text': 'Walk with WASD and press E beside a person, object, or exit. Click a '
                       'marked place to walk there, then press E or click it again to '
                       'interact. The numbered side menu offers the same story choices. '
                       'Unnumbered diamond markers reveal small details; looking closer '
                       'spends no resources.'},
              {'heading': 'Face the enemy',
               'text': "Read each enemy's intention before acting. Click an enemy or press [ "
                       'and ] to target it; Inspect and changing targets cost no turn. Attack '
                       'costs no Focus. Power attacks spend Focus, can interrupt marked '
                       'intentions, and leave you Exposed. Defend halves every attack that '
                       "round and restores 1 Focus. Your background's special ability can be "
                       'used once per battle; companion commands offer other ways to protect '
                       'the party.'},
              {'heading': 'Keep your place on the road',
               'text': 'At story choices, I opens inventory, C shows your character, J opens '
                       'the journal, and R shows the road map. F5 opens manual saves. Escape '
                       'or P opens the pause menu for saving, Settings, and Controls; F1 '
                       'opens Controls at any time. Escape closes a panel. M returns to the '
                       'main menu. Resume checkpoint restores the last automatic story '
                       'checkpoint; you can turn checkpoints off in Settings.'},
              {'heading': 'Make yourself comfortable',
               'text': 'Settings controls reading text size and speed, reduced motion, difficulty, and '
                       'separate music and sound-effect volumes. Sound starts off. F11 '
                       'toggles fullscreen. Screen-reader mode opens the terminal '
                       'presentation on your next launch.'},
              {'heading': 'The road remembers',
               'text': 'Hope, corruption, trust, clues, and surviving companions change the '
                       'paths ahead. Your journal keeps the promises and truths you have '
                       'collected.'}]}

def controls_snapshot() -> dict[str, Any]:
    """Return independent panel data; opening help never changes the journey."""
    return deepcopy(_CONTROLS)
