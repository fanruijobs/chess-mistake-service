from django import template
from django.utils.safestring import mark_safe

from mistakes.board_rendering import render_position_svg


register = template.Library()


@register.simple_tag
def board_svg(puzzle, size=460):
    return mark_safe(render_position_svg(puzzle.fen, orientation=puzzle.game.owner_color, size=int(size)))
