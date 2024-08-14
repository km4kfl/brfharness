# Example

The following example initializes two cards. Sets the transmit data for the first
card then using the second card to recieve the signal. You could also use just a
single card or more than two.

```
    import brfharness
    import numpy as np
    import time

    cards, buffer_samps = brfharness.setup([serial0, serial1], sps, freq, initial_tx_gain)

    sig0 = np.exp(1j * np.linspace(0, np.pi * 2 * args.local_freq_a * t, samps))
    sig1 = np.exp(1j * np.linspace(0, np.pi * 2 * args.local_freq_b * t, samps))

    tx_data0 = sig0 + sig1

    tx_data0 /= np.max(np.abs(tx_data0))
    tx_data0 *= 2000
    tx_data2 = np.zeros((len(tx_data0) * 4), np.int16)
    tx_data2[0::4] = tx_data0.real
    tx_data2[1::4] = tx_data0.imag
    tx_data2[2::4] = 0
    tx_data2[3::4] = 0
    tx_data = tx_data2.tobytes()

    # The TX will keep repeating this data over and over again.
    cards[0].set_tx_data(tx_data)

    time.sleep(3)

    # Grab some samples using the second card that was initialized.
    rx_counter, rx1, rx2 = cards[1].clear_buffer_get_samples(sps)

    # Grab some samples from the first card.
    rx_counter, rx1, rx2 = cards[0].clear_buffer_get_samples(sps)
```