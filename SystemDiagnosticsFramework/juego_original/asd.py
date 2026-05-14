import pygame
pygame.init()

pantalla = pygame.display.set_mode((400, 300))
pygame.display.set_caption("Test pygame")

corriendo = True
while corriendo:
    for evento in pygame.event.get():
        if evento.type == pygame.QUIT:
            corriendo = False

pygame.quit()
