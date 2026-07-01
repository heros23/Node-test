from src.signal_runner import SignalRunner


if __name__ == '__main__':
    runner = SignalRunner()
    sample_prices = [100, 98, 96, 95, 97, 99, 101, 103, 105, 102, 100, 103, 106, 108, 110, 107, 104, 106, 109, 111]
    print(runner.run_once(sample_prices))
