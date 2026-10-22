"""Local keyboard controller for a DJI/Ryze Tello.

Run from the apps repository root:
    python -m klm.connection.tello_controller

Connect the computer to the Tello's Wi-Fi first. The script connects in SDK mode
but does not take off automatically. Press T only when ready to take off.
"""
import sys
import time

try:
    import pygame
    from djitellopy import Tello
except ImportError as exc:
    raise SystemExit(
        "Dependency missing. Activate the apps virtual environment and run: "
        "pip install -r requirements.txt"
    ) from exc


SPEED = 30  # Conservative starting speed; RC control values range from -100 to 100.
FPS = 20


def main():
    tello = Tello()
    connected = False
    flying = False
    battery = None
    last_battery_read = 0.0

    pygame.init()
    screen = pygame.display.set_mode((620, 260))
    pygame.display.set_caption("KLM · DJI Tello Controller")
    font = pygame.font.Font(None, 26)
    clock = pygame.time.Clock()

    try:
        print("Connecting to Tello. Make sure you are connected to TELLO-52D2C8...")
        tello.connect()
        connected = True
        battery = tello.get_battery()
        last_battery_read = time.monotonic()
        print(f"Connected. Battery: {battery}%")
        print("T = take off | SPACE = land | arrows = move | W/S = up/down")
        print("A/D = rotate | ESC = land if flying and quit")
        running = True
        while running:
            left_right = 0
            forward_back = 0
            up_down = 0
            yaw = 0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_t and not flying:
                        confirm = input("Type TAKEOFF to confirm takeoff: ").strip()
                        if confirm == "TAKEOFF":
                            tello.takeoff()
                            flying = True
                    elif event.key == pygame.K_SPACE and flying:
                        tello.land()
                        flying = False

            keys = pygame.key.get_pressed()
            if flying:
                if keys[pygame.K_LEFT]:
                    left_right = -SPEED
                elif keys[pygame.K_RIGHT]:
                    left_right = SPEED
                if keys[pygame.K_UP]:
                    forward_back = SPEED
                elif keys[pygame.K_DOWN]:
                    forward_back = -SPEED
                if keys[pygame.K_w]:
                    up_down = SPEED
                elif keys[pygame.K_s]:
                    up_down = -SPEED
                if keys[pygame.K_a]:
                    yaw = -SPEED
                elif keys[pygame.K_d]:
                    yaw = SPEED

            if connected and flying:
                tello.send_rc_control(left_right, forward_back, up_down, yaw)

            if connected and time.monotonic() - last_battery_read >= 5:
                try:
                    battery = tello.get_battery()
                    last_battery_read = time.monotonic()
                except Exception:
                    pass

            screen.fill((20, 27, 40))
            lines = [
                "KLM · DJI Tello Controller",
                f"Connection: {'connected' if connected else 'disconnected'}",
                f"Battery: {battery if battery is not None else '--'}%",
                f"Flight: {'AIRBORNE' if flying else 'LANDED'}",
                "Arrows move · W/S altitude · A/D rotate",
                "T takeoff (confirmation required) · SPACE land · ESC quit",
            ]
            for i, line in enumerate(lines):
                screen.blit(font.render(line, True, (235, 240, 248)), (22, 22 + i * 36))
            pygame.display.flip()
            clock.tick(FPS)
    except KeyboardInterrupt:
        print("\nController interrupted.")
    finally:
        if connected:
            try:
                if flying:
                    tello.land()
            except Exception as exc:
                print(f"Could not confirm landing: {exc}", file=sys.stderr)
            try:
                tello.end()
            except Exception:
                pass
        pygame.quit()


if __name__ == "__main__":
    main()
