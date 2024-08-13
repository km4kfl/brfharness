import threading
import queue
import bladerf
import numpy as np
from brfharness.bladeandnumpy import BladeRFAndNumpy

def tx_thread(dev, num_buffers, buffer_size, freq, sps, q, qout, tx_gain):
    print('[tx-thread] started')
    dev.sync_config(
        bladerf.ChannelLayout.TX_X2,
        bladerf.Format.SC16_Q11,
        num_buffers=num_buffers,
        buffer_size=buffer_size,
        num_transfers=8,
        stream_timeout=20000
    )

    for ch in [1, 3]:
        dev.set_gain_mode(ch, bladerf.GainMode.Manual)
        dev.set_bias_tee(ch, False)
        dev.set_frequency(ch, freq)
        dev.set_bandwidth(ch, sps)
        dev.set_sample_rate(ch, sps)
        # The board is currently only responding to this initial set
        # of the gain. So, I had to add `tx_gain` as a parameter. I
        # can't seem to get it to set further below.
        dev.set_gain(ch, tx_gain)
        print('tx-gain', dev.get_gain(ch))
        dev.enable_module(ch, True)

    buffer_samps = int((num_buffers * buffer_size) // 8)

    counter = 0

    tx_data = None

    while True:
        cmd = None
        if tx_data is not None:
            try:
                cmd = q.get_nowait()
            except queue.Empty:
                samps = int(len(tx_data) // 4)
                qout.put(('counter', counter))
                # We are counting two channels not total samples.
                counter += samps // 2
                #print('[tx-thread] calling sync_tx')
                dev.sync_tx(tx_data, samps)
        else:
            cmd = q.get()
        if cmd is not None:
            if cmd == 'exit':
                return
            elif len(cmd) > 0 and cmd[0] == 'frequency':
                freq = cmd[1]
                dev.set_frequency(1, freq)
                dev.set_frequency(3, freq)
            elif len(cmd) > 0 and cmd[0] == 'data':
                print('set tx data')
                tx_data = cmd[1]
            elif len(cmd) > 0 and cmd[0] == 'gain':
                dev.set_gain(1, cmd[1])
                dev.set_gain(3, cmd[1])
                print('set-gain', cmd[1])

def rx_thread(dev, num_buffers, buffer_size, freq, sps, rx, tx):
    print('[rx-thread] started')
    dev.sync_config(
        bladerf.ChannelLayout.RX_X2,
        bladerf.Format.SC16_Q11,
        num_buffers=num_buffers,
        buffer_size=buffer_size,
        num_transfers=8,
        stream_timeout=20000
    )

    for ch in [0, 2]:
        dev.set_gain_mode(ch, bladerf.GainMode.Manual)
        dev.set_bias_tee(ch, False)
        dev.set_frequency(ch, freq)
        dev.set_bandwidth(ch, sps)
        dev.set_sample_rate(ch, sps)
        dev.set_gain(ch, 60)
        dev.enable_module(ch, True)
    
    buffer_samps = int(num_buffers * buffer_size / 8)

    counter = 0

    while True:
        sa, sb = dev.sample_as_f64(buffer_samps, 2, 4, 0)
        start_counter = counter 
        counter += len(sa)
        try:
            cmd = rx.get_nowait()
            if cmd[0] == 'request':
                #print(f'[rx-thread] got sample command for {cmd} samples')
                sabuf = [sa]
                sbbuf = [sb]
                got = len(sa)
                while got < cmd[1]:
                    sa, sb = dev.sample_as_f64(buffer_samps, 2, 4, 0)
                    sabuf.append(sa)
                    sbbuf.append(sb)
                    got += len(sa)
                    counter += len(sa)
                sa = np.hstack(sabuf)
                sb = np.hstack(sbbuf)
                tx.put((start_counter, sa[0:cmd[1]], sb[0:cmd[1]]))
            elif cmd[0] == 'frequency':
                print(f'[rx-thread] got frequency command for {cmd[1]:.3f}')
                dev.set_frequency(0, cmd[1])
                dev.set_frequency(2, cmd[1])
            elif cmd == 'exit':
                return
        except queue.Empty:
            pass

def slave_thread(tx_tx, tx_rx, slave_rx, slave_tx):
    """The slave thread.
    """

    def queue_reader(qin, qout, prefix):
        while True:
            item = qin.get()
            qout.put((prefix, item))

    nq = queue.Queue()

    th_a = threading.Thread(target=queue_reader, args=(tx_rx, nq, 'tx_rx'), daemon=True)
    th_b = threading.Thread(target=queue_reader, args=(slave_rx, nq, 'slave_rx'), daemon=True)

    th_a.start()
    th_b.start()

    tx_counter = None

    while True:
        item = nq.get()

        if item[0] == 'tx_rx':
            tx_counter = item[1][1]
        elif item[0] == 'slave_rx':
            if item[1] == 'tx_counter':
                slave_tx.put(tx_counter)
            elif item[1] == 'exit':
                return

class Card:
    tx_tx = None
    tx_rx = None
    rx_tx = None
    rx_rx = None
    slave_tx = None
    slave_rx = None
    tx_th = None
    rx_th = None
    slave_th = None
    dev = None
    buffer_samps = 0

    def clear_buffer_get_samples(self, count):
        assert type(count) is int
        assert count > 0
        self.rx_tx.put(('request', self.buffer_samps))
        self.rx_tx.put(('request', count))
        self.rx_rx.get()
        return self.rx_rx.get()

    def get_samples(self, count):
        assert type(count) is int
        assert count > 0
        self.rx_tx.put(('request', count))
        return self.rx_rx.get()

    def set_tx_data(self, tx_data):
        assert type(tx_data) is bytes
        self.tx_tx.put(('data', tx_data))

    def set_tx_gain(self, gain):
        self.tx_tx.put(('gain', gain))
    
    def exit(self):
        self.tx_tx.put('exit')
        self.rx_tx.put('exit')
        self.slave_tx.put('exit')
        self.join_all()

    def join_all(self):
        self.tx_th.join()
        self.rx_th.join()
        self.slave_th.join()

def setup(serials, sps, freq, initial_tx_gain):
    num_buffers = 16
    buffer_size = 1024 * 32
    buffer_samps = num_buffers * buffer_size
    buffer_samps = int((num_buffers * buffer_size) // 4)

    cards = []

    for serial in serials:
        card = Card()
        cards.append(card)
        card.buffer_samps = buffer_samps
        card.dev = BladeRFAndNumpy(f'libusb:serial={serial}')
        card.tx_tx = queue.Queue()
        card.tx_rx = queue.Queue()
        card.rx_tx = queue.Queue()
        card.rx_rx = queue.Queue()
        card.slave_tx = queue.Queue()
        card.slave_rx = queue.Queue()
        card.tx_th = threading.Thread(
            target=tx_thread,
            args=(
                card.dev,
                num_buffers,
                buffer_size,
                freq,
                sps,
                card.tx_tx,
                card.tx_rx,
                initial_tx_gain,
            ),
            daemon=True
        )
        card.rx_th = threading.Thread(
            target=rx_thread,
            args=(
                card.dev,
                num_buffers,
                buffer_size,
                freq,
                sps,
                card.rx_tx,
                card.rx_rx,
            ),
            daemon=True
        )

        card.slave_th = threading.Thread(
            target=slave_thread,
            args=(
                card.tx_tx, card.tx_rx,
                card.slave_tx, card.slave_rx
            ),
            daemon=True
        )

        card.tx_th.start()
        card.rx_th.start()
        card.slave_th.start()

    return cards, buffer_samps