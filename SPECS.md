I am using a RFSoc 4x2 with the Quantum Instrumentation Control Kit (QICK)
for measuring Microwave resonators and Qubit control. In my lab we have 
three different kind of chips:
- Transmon: A transmon qubit chip with resonators with frequencies of the
order of 7 GHz and qubit energies of 10 GHz. In this case the control 
should be done utilizing the same readout line, because the qubits don't
have a separated control line. We would like to also measure its resonators
and to perform two tone spectroscopy and also Rabi measurements.
- Fluxonium: A fluxonium qubit chip with resonators with frequencies also
of the order of 7 GHz but qubit energies of MHz order. In this case they
have separated control line. We also like to measure its resonators and 
perform two tone and Rabi like in the fluxonium.
- MKIDs: An array of 16 microwave kinetic inductance detectors operating
on the 5 GHz range. In this case we want to perform multiplexation to
measure the I/Q components of the signal of all 16 resonators at the same
time in order to reconstruct images (the number of resonators can change
because we have different chips). What we want to do is similar to what 
has been done in Mazin Lab. We already have a simple implementation in
https://github.com/Fraanco1/mkid_readout, that used a RedPitaya and was
programmed utilizing SystemVerilog. We would like to do something like
that but with QICK, and following Mazin Lab as close as possible to
get the best results.

We have at disponibility real mixers and I/Q mixers and a separate local oscillator
that can generate up to 7 GHz so we can reach the readout frequency using the FPGA + LO.
Take into account that, for fluxonium since we have separated control line one of the DACs
of the RFSoc will be used to generate control tones. 
Instead, with the MKIDs we can generate I/Q signals out of the FPGA using the two DACs and use the I/Q mixers to
reach the frequency.

So, in summary, I want to create a frontend system that enables us to measure
these three king of chips. Since we are familiar with using a Keysight PNA-X N5242B
we would like the interface to resemble these kind of instruments. 
In this computer I have the RFSoc connected with the ip 192.168.3.1 which you can access
via SSH via `ssh xilinx@192.168.3.1`. I have a set of skills installed in order to
implement codebases in the best ways possible. You have available the karpathy guidelines skill,
the frontend design one and also the mattpocock-skills. I want you to use these skills to build
the aplication I am asking for.
Also, you have the QICK documentation on https://docs.qick.dev/latest/, which I encourage you
to research extensively in order to make best use of it.

I want you ask me when there is a design decisition where you are not sure of what to do based on the information I 
gave you.
