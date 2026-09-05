# Theater: AVPro Edge AC-EX40-444-PLUS extenders

## Hardware stages

| Stage | Hardware | Return-audio capability |
|---|---|---|
| Initial | AC-EX40-444-PLUS-T/R | ARC only; cannot transport lossless Dolby TrueHD/Atmos from the television. |
| Planned | AC-EX40-444-PLUS-T2/R2 | eARC; required for final lossless audio validation. |

Confirm the installed revision in the [room record](../README.md#installation-record).

## Connections

```text
Sony HDMI IN 3 (eARC/ARC)
    -> AVPro receiver at television
    -> Category cable
    -> AVPro transmitter at equipment rack
    -> Denon MONITOR 1 HDMI OUT (eARC)
```

Ugoos video connects directly to Sony HDMI IN 4 and does not traverse the extender.

The Sony's `eARC mode: Auto` can remain enabled with the original T/R pair; the connection falls back to ARC. After fitting the T2/R2 pair, refresh the Sony BRAVIA Sync device list, verify the Denon appears and eARC is active, then complete the [room audio validation](../README.md#room-validation).

## Sources

- [AVPro AC-EX40-444-PLUS-T2/R2 product page](https://www.avproglobal.com/products/ac-ex40-444-plus-kit)
- [HDMI Licensing Administrator: eARC capabilities](https://www.hdmi.org/spec2sub/enhancedaudioreturnchannel)
