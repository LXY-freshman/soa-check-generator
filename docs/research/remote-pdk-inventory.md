# Remote PDK and Spectre investigation

调查时间：2026-11-06。调查使用了已授权的远程 PDK 主机和普通 SSH 账号（具体地址、账号和认证信息不写入项目文档）。所有远程操作均为只读，临时 Spectre smoke test 文件写在远程 `/tmp` 后删除。

## Cadence environment

- OS: CentOS Linux 7
- Virtuoso: `IC23.1-64b.ISR6.30`
- Spectre: `23.1.0.242.isr1` (7 Sep 2023)
- Executables: `/opt/Cadence/IC231/tools/dfII/bin/virtuoso`, `/opt/Cadence/SPECTRE231/tools/spectre/bin/spectre`
- `spectre -help assert` documents `sub`, `subs`, `mod`, `dev`, `primitive`, `expr`, `max`, `min`, `duration`, `message`, `level`, `anal_types`, `check_windows`, `safecheck`, and other assert parameters. Severity values include `none`, `notice`, `warning`, `error`, and `fatal`.

## PDK observations

### SMIC BCDA V1.3

The path `/DATA2/BCDA_EXPLORE/PDK/SPDK018MS_and_BCD_Auto_1850_OA_CDS_V1.3_REV0_0` contains several concrete PDK variants, each with `models`, `docs`, `cds.lib`, `techfile.tf`, OA libraries, and a `.devicelist` or `.PDKALL/process/*/device_list`.

For the Epi 1P5M variant:

- `smic18_Epi_1P5M_STM1_1Ba_STM2_HRP3k_MIM15_TYP4.devicelist` has 377 lines and lists CMOS, depletion MOS, LDMOS, DEMOS, resistors, diodes, and related variants.
- `models/spectre/soa_spe.mdl` has 2,348 lines, 1,981 `assert` statements, 152 distinct `sub=` targets, and a `section soa_hv` guarded by `if (soa_check != 0)`.
- `models/spectre/bc018_auto_v1p3_rev0_spe.lib` defines `soa_on` and `soa_off` sections. Both include `soa_spe.mdl` as `section=soa_hv`; `soa_on` sets `soa_check=1`, while `soa_off` sets `soa_check=0`.
- The PDK readme instructs users to include the model library with `section=SOA_ON(OFF)` in a Spectre netlist.
- A Spectre 23.1 smoke test parsed the full file and counted 1,981 asserts. Missing subckt definitions generated expected “assert ignored” warnings; a defined `n18_ckt` target accepted the exact compound-expression syntax.

### UCC21750 SMIC 0.18 BCD V1.20

The PDK contains `models/spectre/soa_spe.mdl` with 1,255 assert statements and the same `section soa_hv`/`soa_check` pattern. It is an older and smaller rule set than BCDA V1.3.

### A6217 / DB HiTek 181abd18BA Rev2p1

The actual directory is `/DATA2/IPLIB_Project/A6217/DPDK_IC6p1_181abd18ba_Rev2p1_0_2019_08_05`. It contains `models/Spectre_lib/181aBD18BA_Rev3p4p1_eSOA.scs` with 1,159 assert statements in a 1,506-line file. It uses `subs=...`, includes temperature and option-dependent expressions, and covers a 5 V/100 V BCD process.

### TPS6282 / DB HiTek 1830BD18BA Rev3p2

`models/Spectre_lib/1830BD18BA_Rev3p2_eSOA.scs` has 671 assert statements in 924 lines and targets 176 distinct subckt names. `Documents/Models/User_Guide_eSOA_IC6p1.pdf` describes including the eSOA model library in the ADE Model Library Setup, enabling/disabling it with a toggle, saving assert information, and viewing eSOA results through the Cadence GUI.

### UNT 55BCD20 V0.53

This PDK contains Spectre SOA parameters inside `models/spe/55bcd20_v0p53_hvmos_spe.mdl` and a user-named `55bcd20_v0p53_mos_spe (soa_lxy).mdl`. The implementation uses `soa_ar`, `soa_br`, `soa_cr`, `soa_dr`, `soa_vdd`, `soa_vgg`, temperature coefficients, and a `gsoa`/`bsource` behavioral source. The user-named file does not contain Spectre `assert` statements. This must be classified as model-internal SOA rather than treated as a missing assert file.

## Consequence for the generator

The first implementation should import an existing SOA artifact when present, detect its mechanism, parse both `sub=` and `subs=`, preserve raw expressions, and generate a versioned derived file. It should only infer missing assertions after the source artifact and model-internal behavior have been classified. A generic parser must not rewrite a model-internal `gsoa` implementation as if it were an eSOA assertion set.

## Rating-pattern caution

The number embedded in a device name is useful evidence but is not automatically the final SOA threshold. In the BCDA V1.3 SOA source:

- `n18_ckt` has approximately 1.98 V gate/body limits and a Vds SOA curve around 3.1–4 V.
- `n50_ckt` has 5.5 V gate limits, but its Vds SOA curve is around 7.3–7.5 V.
- `nld12_iso_ckt` has 5.5 V gate-to-body limits and a Vds SOA curve around 23.9–28.8 V.
- `nde12_iso_ckt` has a similar Vds curve and separate Vgb/Vgs/Vbs/Vbd limits.

Therefore inference must keep at least three concepts separate: the device family/name voltage, the terminal absolute-voltage limit, and the operating-region SOA curve. A name-based value may seed a candidate rule, but an existing SOA source or documented terminal table takes precedence.

The BCDA design manual also explicitly documents a process margin convention for several device families: for example, `nld12` uses a 5 V gate rating with a +10% design margin and a 12–40 V drain family range with a +10% design margin. The same manual reports typical breakdown and DCSOA curves that are much higher or vary with gate voltage. `nld12_iso_ckt` is a 5-terminal D/G/BS/NBL/PSUB device, while `nld12_ls_ckt` is a 3-terminal D/G/BS-tied device; `nde12` has multiple compact, high-side, and low-side topologies. P-device breakdown values use negative polarity. The inference engine must therefore use device topology and terminal semantics before applying a family margin.

The same manual has category-specific evidence outside MOS. The resistor table states that `|Vin-Vout|` must meet the current-density design rule; non-HV 3-terminal resistor bias to substrate is limited to 30 V, while HV resistor Vop is limited to 120 V. It also records approximately 100 uA/um as an allowed DC current density for a TFR example and says its SOA data was still to be provided. These should become resistor-specific inference fields rather than generic MOS voltage rules.

## Device taxonomy found in the supplied PDKs

The BCDA device lists contain these groups: LV/MV MOS, GG MOS, depletion MOS, LDMOS/DEMOS, resistors, diodes, bipolar devices, varactors, MIM capacitors, MOM capacitors, ESD PNP, and pocket/isolation structures. The PDK also exposes multiple topology variants such as ISO, DDNW, HS, LS, compact, low-Vt, and full-isolation devices.

The TPS6282 catalog adds EEPROM/EPROM, ESD MOS, ESD diodes, ESD bipolar structures, SCR-like protection structures, more capacitor families, parasitic devices, isolation rings, and process helper cells. The UNT catalog similarly separates MOS, LDMOS, ESD MOS, ESD diodes, ESD bipolars, parasitic diodes, DTC, resistors, MIM/MOM, varactors, seal-ring and hidden cells.

The importer should therefore classify each discovered cell into at least four scopes: active device, passive device, ESD/protection device, and infrastructure/parasitic/helper cell. All scopes remain searchable, while the default SOA candidate list can focus on active/passive/ESD devices and show infrastructure cells under a separate filter.

PDK naming also encodes composition. Examples include ISO variants with an isolation voltage suffix, DDNW variants, HS/LS variants, and separate `para_*` cells for isolation-ring diodes or parasitic BJTs. The importer should attach these cells to a base device profile instead of exporting them as unrelated devices. A selection such as an ISO MOS must carry the topology and isolation-level metadata into the generated rules.

The BCDA Spectre SOA source contains assert blocks for CMOS, LDMOS, DEMOS and their variants, but no uniform assert blocks for diode, BJT, capacitor, varactor or resistor cells. Those passive and protection categories must use their own model parameters, manual limits, current-density guidance or explicit user rules. The importer should show them as recognized devices with a clear “no executable SOA source” status rather than inventing a common assert template.

The BCDA model readme and manual also provide provenance details useful to the inference engine: model temperature validity is approximately -40 to 150 C; the manual warns that low-temperature BVDS can be about 10% lower than at 25 C and gives typical variation; large LDMOS width can cause current crowding and thermal SOA degradation; TFR guidance gives approximately 100 uA/um DC current density while noting that formal SOA data was pending. These become category-specific evidence and warnings, not universal margins.
