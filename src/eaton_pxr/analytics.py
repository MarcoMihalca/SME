"""
Modul pentru calculul automat al indicatorilor energetici suplimentari
(calitatea energiei electrice, dezechilibre de fază, încărcare disjunctor,
penalizare energie reactivă ANRE, compensare factor de putere) și evaluarea
stărilor de alarmă.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .models import EnergyIndicator, MeasuredValue


def _get_val(by_key: Dict[str, Optional[float]], key: str) -> Optional[float]:
    val = by_key.get(key)
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return float(val)


def compute_energy_indicators(
    measurements: List[MeasuredValue],
    nominal_current_in: float = 1600.0,
) -> List[EnergyIndicator]:
    """
    Calculează automat 8 indicatori energetici suplimentari pe baza măsurătorilor
    în timp real (funcționează atât pentru un Slave ID individual, cât și pentru
    valorile medii de pe întregul lanț).
    """
    by_key: Dict[str, Optional[float]] = {m.key: m.value for m in measurements}

    ia = _get_val(by_key, "I_A")
    ib = _get_val(by_key, "I_B")
    ic = _get_val(by_key, "I_C")
    in_cur = _get_val(by_key, "I_N")

    vab = _get_val(by_key, "V_AB")
    vbc = _get_val(by_key, "V_BC")
    vca = _get_val(by_key, "V_CA")

    van = _get_val(by_key, "V_AN")
    vbn = _get_val(by_key, "V_BN")
    vcn = _get_val(by_key, "V_CN")

    p_tot = _get_val(by_key, "P_TOT")
    q_tot = _get_val(by_key, "Q_TOT")
    s_tot = _get_val(by_key, "S_TOT")
    pf_tot = _get_val(by_key, "PF_TOT")
    freq = _get_val(by_key, "FREQ")

    indicators: List[EnergyIndicator] = []

    # 1. Curent mediu pe fază și Grad de încărcare disjunctor (% din In = 1600 A)
    if ia is not None and ib is not None and ic is not None:
        i_avg = (ia + ib + ic) / 3.0
        i_max = max(ia, ib, ic)
        load_pct = (i_max / nominal_current_in) * 100.0 if nominal_current_in > 0 else 0.0

        if load_pct < 70.0:
            load_status = "ok"
            load_label = f"Normal (Imax={i_max:.1f} A < 70% In)"
        elif load_pct <= 90.0:
            load_status = "warn"
            load_label = f"Încărcare ridicată ({load_pct:.1f}% din In)"
        else:
            load_status = "danger"
            load_label = f"Risc suprasarcină ({load_pct:.1f}% din In)"

        indicators.append(
            EnergyIndicator(
                key="LOAD_PCT",
                name="Grad Încărcare Disjunctor (Imax / In)",
                value=round(load_pct, 2),
                unit="%",
                formatted=f"{load_pct:.2f} % (Imed={i_avg:.1f} A)",
                status=load_status,
                status_label=load_label,
                formula_hint=f"max(IA, IB, IC) / In ({nominal_current_in:.0f} A) × 100",
            )
        )

        # 2. Dezechilibru de curent între faze (NEMA / IEEE)
        if i_avg > 0.5:
            max_dev_i = max(abs(ia - i_avg), abs(ib - i_avg), abs(ic - i_avg))
            i_unbal = (max_dev_i / i_avg) * 100.0
        else:
            i_unbal = 0.0

        if i_unbal < 10.0:
            i_unb_status = "ok"
            i_unb_label = "Echilibrat (< 10%)"
        elif i_unbal <= 20.0:
            i_unb_status = "warn"
            i_unb_label = "Atenție: Dezechilibru moderat (10–20%)"
        else:
            i_unb_status = "danger"
            i_unb_label = "Critic: Dezechilibru sever (> 20%)"

        indicators.append(
            EnergyIndicator(
                key="I_UNBAL",
                name="Dezechilibru Curent Faze (ΔImax / Imed)",
                value=round(i_unbal, 2),
                unit="%",
                formatted=f"{i_unbal:.2f} %",
                status=i_unb_status,
                status_label=i_unb_label,
                formula_hint="max(|Iφ - Imed|) / Imed × 100 (Praguri: 10% / 20%)",
            )
        )
    else:
        i_avg = None
        indicators.append(
            EnergyIndicator(
                key="LOAD_PCT",
                name="Grad Încărcare Disjunctor (Imax / In)",
                value=None,
                unit="%",
                formatted="Indisponibil",
                status="neutral",
                status_label="Date curent indisponibile",
                formula_hint="max(IA, IB, IC) / In × 100",
            )
        )
        indicators.append(
            EnergyIndicator(
                key="I_UNBAL",
                name="Dezechilibru Curent Faze (ΔImax / Imed)",
                value=None,
                unit="%",
                formatted="Indisponibil",
                status="neutral",
                status_label="Date curent indisponibile",
                formula_hint="max(|Iφ - Imed|) / Imed × 100",
            )
        )

    # 3. Dezechilibru Tensiuni Linie-Linie (NEMA / EN 50160)
    if vab is not None and vbc is not None and vca is not None:
        v_ll_avg = (vab + vbc + vca) / 3.0
        if v_ll_avg > 10.0:
            max_dev_vll = max(abs(vab - v_ll_avg), abs(vbc - v_ll_avg), abs(vca - v_ll_avg))
            v_ll_unbal = (max_dev_vll / v_ll_avg) * 100.0
        else:
            v_ll_unbal = 0.0

        if v_ll_unbal < 2.0:
            vll_status = "ok"
            vll_label = f"Normal (< 2%, Vmed={v_ll_avg:.1f} V)"
        elif v_ll_unbal <= 5.0:
            vll_status = "warn"
            vll_label = f"Atenție: Nesimetrie tensiune (2–5%)"
        else:
            vll_status = "danger"
            vll_label = f"Critic: Nesimetrie severă (> 5%)"

        indicators.append(
            EnergyIndicator(
                key="V_LL_UNBAL",
                name="Dezechilibru Tensiune Linie (VAB/VBC/VCA)",
                value=round(v_ll_unbal, 2),
                unit="%",
                formatted=f"{v_ll_unbal:.2f} % (Vmed={v_ll_avg:.1f} V)",
                status=vll_status,
                status_label=vll_label,
                formula_hint="max(|VLL - VLL_med|) / VLL_med × 100 (Standard EN 50160: < 2%)",
            )
        )
    else:
        indicators.append(
            EnergyIndicator(
                key="V_LL_UNBAL",
                name="Dezechilibru Tensiune Linie (VAB/VBC/VCA)",
                value=None,
                unit="%",
                formatted="Indisponibil",
                status="neutral",
                status_label="Date tensiune linie indisponibile",
                formula_hint="max(|VLL - VLL_med|) / VLL_med × 100",
            )
        )

    # 4. Dezechilibru Tensiuni Fază-Nul (VAN/VBN/VCN)
    if van is not None and vbn is not None and vcn is not None:
        v_ln_avg = (van + vbn + vcn) / 3.0
        if v_ln_avg > 10.0:
            max_dev_vln = max(abs(van - v_ln_avg), abs(vbn - v_ln_avg), abs(vcn - v_ln_avg))
            v_ln_unbal = (max_dev_vln / v_ln_avg) * 100.0
        else:
            v_ln_unbal = 0.0

        if v_ln_unbal < 2.0:
            vln_status = "ok"
            vln_label = f"Normal (< 2%, Vmed={v_ln_avg:.1f} V)"
        elif v_ln_unbal <= 5.0:
            vln_status = "warn"
            vln_label = "Atenție: Deplasare neutru / nesimetrie (2–5%)"
        else:
            vln_status = "danger"
            vln_label = "Critic: Nesimetrie tensiune fază (> 5%)"

        indicators.append(
            EnergyIndicator(
                key="V_LN_UNBAL",
                name="Dezechilibru Tensiune Fază-Nul (VAN/VBN/VCN)",
                value=round(v_ln_unbal, 2),
                unit="%",
                formatted=f"{v_ln_unbal:.2f} % (Vmed={v_ln_avg:.1f} V)",
                status=vln_status,
                status_label=vln_label,
                formula_hint="max(|VLN - VLN_med|) / VLN_med × 100",
            )
        )
    else:
        indicators.append(
            EnergyIndicator(
                key="V_LN_UNBAL",
                name="Dezechilibru Tensiune Fază-Nul (VAN/VBN/VCN)",
                value=None,
                unit="%",
                formatted="Indisponibil",
                status="neutral",
                status_label="Date tensiune fază indisponibile",
                formula_hint="max(|VLN - VLN_med|) / VLN_med × 100",
            )
        )

    # 5. Încadrare Factor de Putere (cos φ) & Necesar Compensare Reactivă (Q_comp pt cos φ = 0.95)
    # Dacă PF_TOT este în procente (ex: > 1.05), îl normalizăm la [0..1]
    pf_norm: Optional[float] = None
    if pf_tot is not None:
        pf_abs = abs(pf_tot)
        pf_norm = pf_abs / 100.0 if pf_abs > 1.05 else pf_abs
        pf_norm = min(1.0, max(0.0, pf_norm))
    elif p_tot is not None and s_tot is not None and s_tot > 1.0:
        pf_norm = min(1.0, max(0.0, abs(p_tot) / s_tot))

    if pf_norm is not None:
        if pf_norm >= 0.92:
            pf_status = "ok"
            pf_label = "Fără penalizare ANRE (cos φ ≥ 0.92)"
        elif pf_norm >= 0.65:
            pf_status = "warn"
            pf_label = "Penalizare energie reactivă (0.65 ≤ cos φ < 0.92)"
        else:
            pf_status = "danger"
            pf_label = "Penalizare triplă critică (cos φ < 0.65)"

        # Calcul Q_comp necesar pentru a aduce cos φ la 0.95
        q_comp_kvar = 0.0
        if p_tot is not None and abs(p_tot) > 1.0 and 0.05 < pf_norm < 0.95:
            phi_actual = math.acos(pf_norm)
            phi_target = math.acos(0.95)
            q_comp_w = abs(p_tot) * (math.tan(phi_actual) - math.tan(phi_target))
            q_comp_kvar = max(0.0, q_comp_w / 1000.0)

        indicators.append(
            EnergyIndicator(
                key="PF_QUALITY",
                name="Eficiență Factor de Putere & Compensare (Qcomp)",
                value=round(pf_norm, 3),
                unit="",
                formatted=f"cos φ = {pf_norm:.3f} (Qcomp ≈ {q_comp_kvar:.2f} kVAr)",
                status=pf_status,
                status_label=pf_label,
                formula_hint="Prag ANRE cos φ = 0.92 | Qcomp = P × (tan φ1 - tan φ2) pt. ținta 0.95",
            )
        )
    else:
        indicators.append(
            EnergyIndicator(
                key="PF_QUALITY",
                name="Eficiență Factor de Putere & Compensare (Qcomp)",
                value=None,
                unit="",
                formatted="Indisponibil",
                status="neutral",
                status_label="Date factor de putere indisponibile",
                formula_hint="Prag ANRE cos φ = 0.92",
            )
        )

    # 6. Încărcare Conductor Nul față de Curentul Mediu de Fază (IN / Imed)
    if in_cur is not None and i_avg is not None:
        if i_avg > 0.5:
            in_ratio = (abs(in_cur) / i_avg) * 100.0
        else:
            in_ratio = 0.0

        if in_ratio < 15.0:
            in_status = "ok"
            in_label = f"Normal (IN={in_cur:.1f} A < 15% Imed)"
        elif in_ratio <= 50.0:
            in_status = "warn"
            in_label = f"Circulație pe nul / armonici ord. 3 ({in_ratio:.1f}%)"
        else:
            in_status = "danger"
            in_label = f"Suprasolicitare conductor nul ({in_ratio:.1f}%)"

        indicators.append(
            EnergyIndicator(
                key="IN_RATIO",
                name="Încărcare Conductor Nul (IN / Imed)",
                value=round(in_ratio, 2),
                unit="%",
                formatted=f"{in_ratio:.2f} % ({in_cur:.1f} A)",
                status=in_status,
                status_label=in_label,
                formula_hint="IN / Imed × 100 (Valori mari indică nesimetrie sau armonici de ordin 3)",
            )
        )
    else:
        indicators.append(
            EnergyIndicator(
                key="IN_RATIO",
                name="Încărcare Conductor Nul (IN / Imed)",
                value=None,
                unit="%",
                formatted="Indisponibil",
                status="neutral",
                status_label="Date curent nul indisponibile",
                formula_hint="IN / Imed × 100",
            )
        )

    # 7. Abatere Frecvență Rețea față de 50.00 Hz (EN 50160)
    if freq is not None and freq > 10.0:
        df = freq - 50.0
        abs_df = abs(df)
        if abs_df <= 0.2:
            f_status = "ok"
            f_label = "Frecvență stabilă (50 Hz ± 0.2 Hz)"
        elif abs_df <= 0.5:
            f_status = "warn"
            f_label = "Abatere admisibilă EN 50160 (±1%)"
        else:
            f_status = "danger"
            f_label = "În afara limitelor EN 50160 (> ±0.5 Hz)"

        sign = "+" if df >= 0 else ""
        indicators.append(
            EnergyIndicator(
                key="FREQ_DEV",
                name="Abatere Frecvență Rețea (Δf față de 50 Hz)",
                value=round(df, 3),
                unit="Hz",
                formatted=f"{sign}{df:.2f} Hz ({freq:.2f} Hz)",
                status=f_status,
                status_label=f_label,
                formula_hint="Δf = f - 50.00 Hz (Limita EN 50160: ±0.50 Hz)",
            )
        )
    else:
        indicators.append(
            EnergyIndicator(
                key="FREQ_DEV",
                name="Abatere Frecvență Rețea (Δf față de 50 Hz)",
                value=None,
                unit="Hz",
                formatted="Indisponibil",
                status="neutral",
                status_label="Date frecvență indisponibile",
                formula_hint="Δf = f - 50.00 Hz",
            )
        )

    # 8. Putere Deformantă / Reziduu Armonic din Triunghiul Puterilor: D = sqrt(max(0, S^2 - P^2 - Q^2))
    if p_tot is not None and q_tot is not None and s_tot is not None:
        s_fund = math.hypot(p_tot, q_tot)
        d_sq = max(0.0, (s_tot ** 2) - (s_fund ** 2))
        d_va = math.sqrt(d_sq)
        d_pct = (d_va / s_tot) * 100.0 if s_tot > 1.0 else 0.0

        if d_pct < 5.0:
            d_status = "ok"
            d_label = f"Distorsiune redusă ({d_pct:.1f}% din S)"
        elif d_pct <= 15.0:
            d_status = "warn"
            d_label = f"Prezență armonici ({d_pct:.1f}% din S)"
        else:
            d_status = "danger"
            d_label = f"Regim puternic deformant ({d_pct:.1f}% din S)"

        indicators.append(
            EnergyIndicator(
                key="D_POWER",
                name="Putere Deformantă Estimată (D)",
                value=round(d_va, 1),
                unit="VA",
                formatted=f"{d_va:.1f} VA ({d_pct:.1f}% din S)",
                status=d_status,
                status_label=d_label,
                formula_hint="D = √(S² - P² - Q²) — estimează distorsiunea armonică globală",
            )
        )
    else:
        indicators.append(
            EnergyIndicator(
                key="D_POWER",
                name="Putere Deformantă Estimată (D)",
                value=None,
                unit="VA",
                formatted="Indisponibil",
                status="neutral",
                status_label="Date puteri P/Q/S indisponibile",
                formula_hint="D = √(S² - P² - Q²)",
            )
        )

    return indicators


def evaluate_alarm_state(
    devices: Dict[str, Dict[str, Any]],
    chain_alert: Dict[str, Any],
    halted: bool,
) -> Dict[str, Any]:
    """
    Evaluează dacă există o stare activă de alarmă în sistem (declanșare disjunctor,
    alarmă PXR25, întrerupere lanț RS-485 sau indicatori energetici în stare critică)
    pentru activarea alertei sonore și vizuale din Dashboard.
    """
    reasons: List[str] = []
    severity = "normal"

    if halted:
        reasons.append("Citire oprită pentru intervenție hardware pe magistrala RS-485.")
        severity = "critical"

    if chain_alert.get("pending") and chain_alert.get("reason") == "chain_break":
        msg = chain_alert.get("message") or "Întrerupere detectată în lanțul Modbus RS-485!"
        reasons.append(msg)
        severity = "critical"

    for sid_str, dev in sorted(devices.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        st = dev.get("status_info") or {}
        prim = st.get("Stare Principală Disjunctor", "")
        sec = st.get("Stare Secundară Unitate PXR", "")
        cause = st.get("Cauză Stare / Eveniment", "")

        # Cod 0x03 = Declanșat/Tripat, 0x04 = Alarmă activă
        if any(code in prim for code in ("[0x03]", "[0x04]", "Tripped", "Declanșat", "Alarm")):
            reasons.append(f"Dispozitiv ID #{sid_str}: {prim} ({cause})")
            severity = "critical"
        elif any(code in sec for code in ("[0x02]", "[0x08]", "[0x01]", "Alarm", "Pre-alarmă", "Eroare")):
            reasons.append(f"Dispozitiv ID #{sid_str} (Stare secundară): {sec} ({cause})")
            if severity != "critical":
                severity = "warning"
        elif cause and "[0x0000]" not in cause and "Normal" not in cause:
            reasons.append(f"Dispozitiv ID #{sid_str} (Eveniment activ): {cause}")
            if severity != "critical":
                severity = "warning"

        # Verificăm și indicatorii energetici critici ('danger')
        for ind in dev.get("energy_indicators", []):
            if ind.get("status") == "danger":
                reasons.append(
                    f"Dispozitiv ID #{sid_str} — {ind.get('name')}: {ind.get('formatted')} ({ind.get('status_label')})"
                )
                if severity != "critical":
                    severity = "warning"

    active = len(reasons) > 0
    signature = "|".join(reasons) if active else ""
    return {
        "active": active,
        "severity": severity,
        "count": len(reasons),
        "reasons": reasons,
        "signature": signature,
    }
