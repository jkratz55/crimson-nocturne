"""Regenerate every procedural asset: `python3 tools/asset_pipeline/build_all.py`.

Each module also runs on its own (`python3 tools/asset_pipeline/<module>.py`)
and writes only its own outputs.
"""
import audio
import backgrounds
import enemies
import equipment
import fx
import hero
import items
import props
import tiles
import ui

if __name__ == "__main__":
    hero.build()
    enemies.build()
    fx.build()
    items.build()
    props.build()
    ui.build()
    equipment.build()
    tiles.build()
    backgrounds.build()
    audio.build()
    print("All assets generated.")
