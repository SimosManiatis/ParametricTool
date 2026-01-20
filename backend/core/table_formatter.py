
def format_table_header(num_windows, num_shading, num_context, month):
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    month_name = month_names[month - 1] if 1 <= month <= 12 else "Unknown"

    lines = []
    lines.append("=" * 80)
    lines.append("NEN 5060 WINDOW SHADING CLASSIFICATION v7.0 (External Service)")
    lines.append("=" * 80)
    lines.append("")
    lines.append("INPUT SUMMARY:")
    lines.append("  Windows: {}".format(num_windows))
    lines.append("  Shading devices: {}".format(num_shading))
    lines.append("  Context buildings: {}".format(num_context))
    lines.append("  Analysis month: {} ({})".format(month, month_name))
    lines.append("")
    lines.append("METHODOLOGY:")
    lines.append("  - Context obstruction: blocks sky from 0deg up to context_angle")
    lines.append("  - Shading obstruction: blocks sky from shading_angle up to 90deg")
    lines.append("  - Comparison: context_blocked vs shading_blocked (= 90 - shading_angle)")
    lines.append("  - Threshold for 'significant': 20.0deg")
    lines.append("")
    lines.append("=" * 80)
    lines.append("")
    lines.append("PREPARING GEOMETRY... (Done)")
    lines.append("")
    lines.append("PROCESSING WINDOWS...")
    lines.append("-" * 80)
    lines.append("{:>5} {:>7} {:>7} {:>8} {:>8} {:>14} {:>8} {:>7}".format(
        "Win", "Ctx", "Shd", "Ctx_blk", "Shd_blk", "Dominant", "Class", "Fsh"))
    lines.append("-" * 80)
    return lines  # Return list directly

def format_table_row(i, result):
    cls_map = {
        "Minimale Belemmering": "Min",
        "Overstek": "Ove",
        "Belemmering": "Bel",
        "Error": "Err"
    }
    cls_abbrev = cls_map.get(result.get('classification'), "???")
    
    # EXACT TRUNCATION as per Internal Script
    dom_full = result.get('dominant', "")
    dom_display = dom_full[:14]
    
    return "{:>5} {:>7.1f} {:>7.1f} {:>8.1f} {:>8.1f} {:>14} {:>8} {:>7.3f}".format(
        i,
        result.get('context_angle', 0.0),
        result.get('shading_angle', 0.0),
        result.get('context_blocked', 0.0),
        result.get('shading_blocked', 0.0),
        dom_display,
        cls_abbrev,
        result.get('fsh_factor', 1.0)
    )

def format_table_summary(results):
    count_min = sum(1 for r in results if r.get('classification') == "Minimale Belemmering")
    count_ove = sum(1 for r in results if r.get('classification') == "Overstek")
    count_bel = sum(1 for r in results if r.get('classification') == "Belemmering")
    count_err = sum(1 for r in results if r.get('classification') == "Error")
    total = max(1, len(results))
    
    context_angles = [r.get('context_angle', 0.0) for r in results]
    shading_angles = [r.get('shading_angle', 0.0) for r in results]
    fsh_factors = [r.get('fsh_factor', 1.0) for r in results]
    
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append("SUMMARY")
    lines.append("=" * 80)
    
    lines.append("\nCLASSIFICATION DISTRIBUTION:")
    lines.append("  Minimale Belemmering: {:>4} windows ({:.1f}%)".format(count_min, 100.0 * count_min / total))
    lines.append("  Overstek:             {:>4} windows ({:.1f}%)".format(count_ove, 100.0 * count_ove / total))
    lines.append("  Belemmering:          {:>4} windows ({:.1f}%)".format(count_bel, 100.0 * count_bel / total))
    if count_err > 0:
        lines.append("  Errors:               {:>4} windows".format(count_err))
        
    if context_angles:
        avg_ctx = sum(context_angles) / len(context_angles)
        lines.append("\nCONTEXT OBSTRUCTION:")
        lines.append("  Raw angles:  min={:.1f}deg  max={:.1f}deg  avg={:.1f}deg".format(min(context_angles), max(context_angles), avg_ctx))

    if shading_angles:
        avg_shd = sum(shading_angles) / len(shading_angles)
        lines.append("\nSHADING OBSTRUCTION:")
        lines.append("  Raw angles:  min={:.1f}deg  max={:.1f}deg  avg={:.1f}deg".format(min(shading_angles), max(shading_angles), avg_shd))

    if fsh_factors:
        avg_fsh = sum(fsh_factors) / len(fsh_factors)
        lines.append("\nFSH FACTORS:")
        lines.append("  Range: {:.3f} to {:.3f}".format(min(fsh_factors), max(fsh_factors)))
        lines.append("  Average: {:.3f}".format(avg_fsh))
        
    lines.append("\n" + "=" * 80)
    return lines # Return list directly
