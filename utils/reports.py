"""CSV and PDF report builders."""
import csv
import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import data as D

CSV_FIELDS = [
    "id", "created_at", "created_by", "meal_date", "meal_type", "day_type", "menu_type",
    "students_present", "food_prepared_kg", "predicted_wastage_kg", "est_consumption_kg",
    "wastage_pct", "recommendation", "notes", "model_trained_at", "dataset_source",
]


def _safe_cell(value):
    """Neutralise spreadsheet formula injection."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def build_csv(predictions):
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(CSV_FIELDS)
    for p in predictions:
        writer.writerow([_safe_cell(p.get(f, "")) for f in CSV_FIELDS])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")   # BOM so Excel reads UTF-8


# --------------------------------------------------------------------------
GREEN = colors.HexColor("#1f6b45")
LIGHT = colors.HexColor("#eef5f0")


def _table(rows, col_widths=None, align_right_from=1):
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9d6cd")),
        ("ALIGN", (align_right_from, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build_pdf(predictions, dataset_summary, dataset_meta, metrics, max_rows=200):
    buf = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(15 * mm, 8 * mm, "Smart Mess Food Wastage Prediction and Analysis System")
        canvas.drawRightString(landscape(A4)[0] - 15 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm, title="Smart Mess Report")
    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Title"], textColor=GREEN, fontSize=20, alignment=0)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], textColor=GREEN, fontSize=13, spaceBefore=10)
    body = ParagraphStyle("body", parent=base["BodyText"], fontSize=9, leading=12)
    warn = ParagraphStyle("warn", parent=body, textColor=colors.HexColor("#9a3412"))

    story = [Paragraph("Smart Mess - Food Wastage Report", h1),
             Paragraph(f"Generated {datetime.now():%Y-%m-%d %H:%M}", body)]

    # --- Dataset summary --------------------------------------------------
    story.append(Paragraph("1. Dataset summary statistics", h2))
    story.append(Paragraph(f"Data source: {escape(D.source_label(dataset_meta))}"
                           + (f" ({escape(str(dataset_meta.get('filename')))})" if dataset_meta.get("filename") else ""), body))
    if D.is_synthetic(dataset_meta):
        story.append(Paragraph("NOTE: the dataset is SYNTHETIC demo data. Figures below do not describe a real mess.", warn))
    if dataset_summary:
        t = dataset_summary["totals"]
        story.append(Spacer(1, 4))
        story.append(_table([
            ["Meals", "Days", "Student-meals", "Prepared (kg)", "Wasted (kg)", "Consumed (kg)", "Wastage %"],
            [f"{t['meals']:,}", f"{t['days']:,}", f"{t['student_meals']:,}", f"{t['prepared']:,.1f}",
             f"{t['wasted']:,.1f}", f"{t['consumed']:,.1f}", f"{t['wastage_pct']:.2f}"],
        ], align_right_from=0))
        story.append(Spacer(1, 6))
        rows = [["Meal", "Meals", "Prepared (kg)", "Wasted (kg)", "Consumed (kg)", "Wastage %"]]
        for m in dataset_summary["meal"]:
            rows.append([m["meal_type"], f"{m['meals']:,}", f"{m['prepared']:,.1f}", f"{m['wasted']:,.1f}",
                         f"{m['consumed']:,.1f}", f"{m['wastage_pct']:.2f}"])
        story.append(_table(rows))
    else:
        story.append(Paragraph("No valid dataset is available.", body))

    # --- Model performance ------------------------------------------------
    story.append(Paragraph("2. Model performance", h2))
    if metrics:
        story.append(Paragraph(
            f"Random Forest Regressor trained {escape(metrics['trained_at'].replace('T', ' '))} on {metrics['n_train']:,} rows and "
            f"evaluated on {metrics['n_test']:,} held-out rows ({int(metrics['test_size'] * 100)}% test split, "
            f"random_state={metrics['random_state']}). Data source at training time: "
            f"{escape(D.SOURCE_LABELS.get(metrics.get('dataset_source'), 'unknown'))}.", body))
        story.append(Spacer(1, 4))
        story.append(_table([
            ["R2 score", "MAE (kg)", "MSE (kg2)", "RMSE (kg)", "Baseline MAE (kg)", "CV R2 (train, 5-fold)"],
            [f"{metrics['r2']:.4f}", f"{metrics['mae']:.3f}", f"{metrics['mse']:.3f}", f"{metrics['rmse']:.3f}",
             f"{metrics['baseline_mae']:.3f}", f"{metrics['cv_r2_mean']:.3f} +/- {metrics['cv_r2_std']:.3f}"],
        ], align_right_from=0))
        if metrics.get("dataset_source") == "synthetic_demo":
            story.append(Paragraph("These metrics were computed on SYNTHETIC demo data and do not reflect real-world accuracy.", warn))
    else:
        story.append(Paragraph("The model has not been trained yet, so no performance metrics are available.", body))
    story.append(Paragraph("Model performance depends on dataset quality and size; more (and cleaner) real records "
                           "generally give more reliable predictions.", body))

    # --- Predictions ------------------------------------------------------
    story.append(Paragraph("3. Prediction history", h2))
    if predictions:
        n = len(predictions)
        avg_pct = sum(p["wastage_pct"] for p in predictions) / n
        total_kg = sum(p["predicted_wastage_kg"] for p in predictions)
        story.append(Paragraph(
            f"{n} prediction(s) saved. Average predicted wastage: {avg_pct:.2f}%. "
            f"Total predicted wastage across them: {total_kg:,.2f} kg."
            + (f" Showing the latest {max_rows}." if n > max_rows else ""), body))
        story.append(Spacer(1, 4))
        rows = [["ID", "Created", "Meal date", "Meal", "Day", "Menu", "Students", "Prepared kg",
                 "Pred. waste kg", "Consumption kg", "Waste %"]]
        for p in predictions[:max_rows]:
            rows.append([p["id"], p["created_at"].replace("T", " "), p["meal_date"], p["meal_type"],
                         p["day_type"], p["menu_type"], p["students_present"], f"{p['food_prepared_kg']:.2f}",
                         f"{p['predicted_wastage_kg']:.2f}", f"{p['est_consumption_kg']:.2f}",
                         f"{p['wastage_pct']:.2f}"])
        widths = [10, 34, 24, 22, 22, 20, 20, 24, 26, 28, 18]
        story.append(_table(rows, [w * mm for w in widths], align_right_from=6))
    else:
        story.append(Paragraph("No predictions have been saved yet.", body))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
