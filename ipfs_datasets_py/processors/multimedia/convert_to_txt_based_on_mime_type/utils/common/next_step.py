import re


def next_step(message: str, step: int = None, stop: bool = False) -> None:
    """
    Display a message and optionally prompt the user to continue to the next step in a linear, multi-step process.
    Putting in 'Step 1' in the message will automatically increment the step counter.
    The function behaviors changes based on the 'stop' parameter:
    - If stop is False, it simply logs the message and returns.
    - If stop is True, it prompts the user to continue and raises a KeyboardInterrupt if they decline.

    Args:
        message (str): The message to display.
        step (int, optional): The step number. If provided, it will be used in the prompt.
        stop (bool, optional): If True, the function will prompt for user input before continuing.

    Returns:
        None

    Raises:
        KeyboardInterrupt: If the user chooses not to continue when prompted.

    Example:
        # Log a message without stopping
        next_step("Processing data...")

        # Prompt user to continue to the next step
        next_step("Step 1: Data collection complete", stop=True)

        # Manually specify step number
        next_step("Analyzing results", step=3, stop=True)
    """
    # Define regex to match the "Step X" format in the message.
    step_pattern = re.compile(r'^Step \d+', flags=re.IGNORECASE)
    match = re.match(step_pattern, message)
    asterisks = '*' * len(message)

    if stop:
        if match: # If the message contains "Step X", extract the step number.
            step = int(re.search(r'\d+', match.group()).group())
        if match or step:
            current_step = step - 1
            result = input(f"{asterisks}\n{message}\n{asterisks}\nContinue to Step {step}? y/n: ")
            if result != "y": # If the user does not enter 'y', raise a KeyboardInterrupt.
                raise KeyboardInterrupt(f"Program stopped at Step {current_step}.")
            else:
                print(message)
                return
        else: # If the message does not contain "Step X" and no step number is provided, prompt the user to continue.
            result = input(f"Continue next step? y/n: ")
            if result != "y":
                raise KeyboardInterrupt(f"Program stopped at current step.")
            else:
                print(message)
                return
    else:
        print(message)
        return
