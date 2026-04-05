import chess
import chess.svg
import re


LIGHT_SQUARE = "#eeeed2"
DARK_SQUARE = "#769656"
COORD_COLOR = "#4f5f45"


def render_position_svg(fen: str, orientation: str = "white", size: int = 460) -> str:
    board = chess.Board(fen)
    board_orientation = chess.BLACK if orientation == "black" else chess.WHITE
    svg = chess.svg.board(
        board=board,
        orientation=board_orientation,
        coordinates=True,
        size=size,
        colors={
            "square light": LIGHT_SQUARE,
            "square dark": DARK_SQUARE,
            "coord": COORD_COLOR,
        },
    )
    return _transparentize_outer_background(svg)


def _transparentize_outer_background(svg: str) -> str:
    svg = re.sub(
        r'(<rect\s+width="100%"\s+height="100%"\s+fill=")([^"]+)("\s*/>)',
        r"\1transparent\3",
        svg,
        count=1,
    )
    return re.sub(
        r'(<rect\s+x="7\.5"\s+y="7\.5"\s+width="375"\s+height="375"\s+fill="none"\s+stroke=")([^"]+)("\s+stroke-width="15"\s*/>)',
        r'\1transparent\3',
        svg,
        count=1,
    )
