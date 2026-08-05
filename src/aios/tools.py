"""Native agent tools — interactive helpers run inside the AiosDeck process."""


def ask_user(prompt_text: str) -> str:
    print(prompt_text)
    return input()
