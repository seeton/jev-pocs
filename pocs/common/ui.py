"""Shared pygame button controls."""
import pygame

def buttons(screen, font, items):
    """Draw controls and return the same rectangles used for mouse hit testing."""
    areas = {}
    for action, label, rect in items:
        box = pygame.Rect(rect)
        color = '#314d6b' if box.collidepoint(pygame.mouse.get_pos()) else '#203650'
        pygame.draw.rect(screen, color, box, border_radius=9)
        pygame.draw.rect(screen, '#55799c', box, width=1, border_radius=9)
        rendered = font.render(label, True, '#e5edf9')
        screen.blit(rendered, rendered.get_rect(center=box.center))
        areas[action] = box
    return areas


def clicked(event, areas):
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        return next((action for action, rect in areas.items() if rect.collidepoint(event.pos)), None)
    return None
