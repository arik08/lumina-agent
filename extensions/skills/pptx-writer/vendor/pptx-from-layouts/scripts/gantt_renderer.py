#!/usr/bin/env python3
"""
gantt_renderer.py: Shared Gantt chart rendering module.

This module provides common Gantt chart rendering functionality used by:
- gantt-timeline skill (standalone Gantt from markdown)
- pptx-from-layout pipeline (Gantt rendering for timeline slides)

Extracted from generate_gantt.py to enable reuse across skills.
"""

from dataclasses import dataclass, field
from pptx.util import Pt, Inches
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor

# Import pptx_compat from scripts directory
import sys
from pathlib import Path
_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from pptx_compat import parse_xml, get_cell_properties


# =============================================================================
# INNER CHAPTER BRAND COLORS
# =============================================================================

class ICColors:
    """Inner Chapter brand color palette for Gantt charts."""
    BLACK = RGBColor(0x00, 0x00, 0x00)
    WHITE = RGBColor(0xFF, 0xFF, 0xFF)
    CREAM = RGBColor(0xF5, 0xF5, 0xF0)

    # Table-specific
    HEADER_BG = RGBColor(0x00, 0x00, 0x00)       # Black header
    HEADER_TEXT = RGBColor(0xFF, 0xFF, 0xFF)     # White text on header
    SUBHEADER_BG = RGBColor(0xF5, 0xF5, 0xF5)    # Light gray for week row

    # Duration fills
    WORK_FILL = RGBColor(0xC0, 0xC0, 0xC0)       # Gray for work periods
    MILESTONE_FILL = RGBColor(0x8B, 0x1A, 0x1A)  # Dark red for milestones
    HOLIDAY_FILL = RGBColor(0xFF, 0xE4, 0xE1)    # Light pink for holidays

    # Borders
    BORDER_COLOR = RGBColor(0xD0, 0xD0, 0xD0)    # Light gray borders

    # Fonts
    FONT_FAMILY = "Aptos"
    FONT_SIZE_HEADER = 11
    FONT_SIZE_BODY = 10


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Task:
    """Represents a single task in the Gantt chart."""
    name: str
    start: int  # Column index (0-based, after label columns)
    end: int    # Column index (inclusive)
    is_milestone: bool = False
    label: str = ""  # Optional label to display in the duration cell


@dataclass
class Phase:
    """Represents a phase containing multiple tasks."""
    name: str
    tasks: list = field(default_factory=list)

    def add_task(self, task: Task):
        self.tasks.append(task)


@dataclass
class GanttData:
    """Complete Gantt chart data structure."""
    title: str = "Timeline"
    name: str = ""
    is_week_based: bool = True
    columns: list = field(default_factory=list)  # Column headers
    month_spans: list = field(default_factory=list)  # (month_name, start_col, end_col)
    phases: list = field(default_factory=list)
    holidays: dict = field(default_factory=dict)  # column_index -> label

    @property
    def has_phases(self) -> bool:
        return len(self.phases) > 1 or (len(self.phases) == 1 and self.phases[0].name)

    @property
    def all_tasks(self) -> list:
        tasks = []
        for phase in self.phases:
            tasks.extend(phase.tasks)
        return tasks

    @property
    def num_time_columns(self) -> int:
        return len(self.columns)

    @property
    def num_label_columns(self) -> int:
        """Number of columns before time columns (phase + task name)."""
        return 2 if self.has_phases else 1


# =============================================================================
# CELL STYLING HELPERS
# =============================================================================

def set_cell_fill(cell, color: RGBColor):
    """Set cell background fill color using python-pptx native API."""
    cell.fill.solid()
    cell.fill.fore_color.rgb = color


def set_cell_border(cell, color: RGBColor, width: Pt = Pt(0.5)):
    """Set cell borders."""
    tcPr = get_cell_properties(cell)

    # Border XML
    borders = ['lnL', 'lnR', 'lnT', 'lnB']
    for border in borders:
        border_xml = parse_xml(
            f'<a:{border} xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" w="{width.emu}">'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f'</a:{border}>'
        )
        # Remove existing
        for child in list(tcPr):
            if border in child.tag:
                tcPr.remove(child)
        tcPr.append(border_xml)


def style_cell_text(cell, text: str, bold: bool = False, font_size: int = 10,
                    color: RGBColor = ICColors.BLACK, align: str = 'left'):
    """Set cell text with formatting."""
    cell.text = text

    paragraph = cell.text_frame.paragraphs[0]
    paragraph.font.name = ICColors.FONT_FAMILY
    paragraph.font.size = Pt(font_size)
    paragraph.font.bold = bold
    paragraph.font.color.rgb = color

    if align == 'center':
        paragraph.alignment = PP_ALIGN.CENTER
    elif align == 'right':
        paragraph.alignment = PP_ALIGN.RIGHT
    else:
        paragraph.alignment = PP_ALIGN.LEFT

    # Vertical alignment
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE


# =============================================================================
# GANTT TABLE CREATION
# =============================================================================

def create_gantt_table(slide, gantt: GanttData, left, top, width, height):
    """Create and populate the Gantt chart table.

    Args:
        slide: PowerPoint slide object
        gantt: GanttData structure with all chart data
        left: Left position (Inches or EMU)
        top: Top position (Inches or EMU)
        width: Table width (Inches or EMU)
        height: Table height (Inches or EMU)

    Returns:
        The created table shape
    """
    num_label_cols = gantt.num_label_columns
    num_time_cols = gantt.num_time_columns
    total_cols = num_label_cols + num_time_cols

    # Calculate rows: header rows + task rows
    has_month_row = len(gantt.month_spans) > 0
    header_rows = 2 if has_month_row else 1
    task_rows = len(gantt.all_tasks)
    total_rows = header_rows + task_rows

    if total_rows == 0 or total_cols == 0:
        return None

    # Create table shape
    table_shape = slide.shapes.add_table(total_rows, total_cols, left, top, width, height)
    table = table_shape.table

    # Calculate column widths
    label_width = Inches(1.8) if gantt.has_phases else Inches(2.2)
    task_col_width = Inches(1.8)

    if gantt.has_phases:
        available_width = width - label_width - task_col_width
    else:
        available_width = width - task_col_width

    # Handle Inches conversion
    if hasattr(available_width, 'emu'):
        available_width = available_width.emu
    if hasattr(width, 'emu'):
        width_emu = width.emu
    else:
        width_emu = width

    time_col_width = available_width / num_time_cols if num_time_cols > 0 else Inches(0.5).emu

    # Set column widths
    col_idx = 0
    if gantt.has_phases:
        table.columns[col_idx].width = int(label_width.emu if hasattr(label_width, 'emu') else label_width)
        col_idx += 1
        table.columns[col_idx].width = int(task_col_width.emu if hasattr(task_col_width, 'emu') else task_col_width)
        col_idx += 1
    else:
        table.columns[col_idx].width = int(task_col_width.emu if hasattr(task_col_width, 'emu') else task_col_width)
        col_idx += 1

    for i in range(num_time_cols):
        table.columns[col_idx + i].width = int(time_col_width)

    # === HEADER ROWS ===
    row_idx = 0

    if has_month_row:
        # Month header row
        for col in range(total_cols):
            cell = table.cell(row_idx, col)
            set_cell_fill(cell, ICColors.HEADER_BG)
            set_cell_border(cell, ICColors.BORDER_COLOR)

        # Merge and label month spans
        for month_name, start_col, end_col in gantt.month_spans:
            actual_start = num_label_cols + start_col
            actual_end = num_label_cols + end_col

            if actual_start <= actual_end < total_cols:
                # Merge cells
                if actual_start < actual_end:
                    start_cell = table.cell(row_idx, actual_start)
                    end_cell = table.cell(row_idx, actual_end)
                    start_cell.merge(end_cell)

                cell = table.cell(row_idx, actual_start)
                style_cell_text(cell, month_name, bold=True,
                               font_size=ICColors.FONT_SIZE_HEADER,
                               color=ICColors.HEADER_TEXT, align='center')

        # Empty cells for label columns
        for col in range(num_label_cols):
            cell = table.cell(row_idx, col)
            style_cell_text(cell, "", color=ICColors.HEADER_TEXT)

        row_idx += 1

    # Week/date subheader row
    for col in range(total_cols):
        cell = table.cell(row_idx, col)
        set_cell_fill(cell, ICColors.SUBHEADER_BG)
        set_cell_border(cell, ICColors.BORDER_COLOR)

    # Label column headers
    if gantt.has_phases:
        style_cell_text(table.cell(row_idx, 0), "STAGE", bold=True, font_size=ICColors.FONT_SIZE_BODY)
        style_cell_text(table.cell(row_idx, 1), "ACTIVITY", bold=True, font_size=ICColors.FONT_SIZE_BODY)
    else:
        style_cell_text(table.cell(row_idx, 0), "ACTIVITY", bold=True, font_size=ICColors.FONT_SIZE_BODY)

    # Week/date headers
    for i, col_header in enumerate(gantt.columns):
        col = num_label_cols + i
        cell = table.cell(row_idx, col)
        style_cell_text(cell, col_header, bold=False,
                       font_size=ICColors.FONT_SIZE_BODY, align='center')

        # Holiday column highlighting
        if i in gantt.holidays:
            set_cell_fill(cell, ICColors.HOLIDAY_FILL)

    row_idx += 1

    # === TASK ROWS ===
    for phase in gantt.phases:
        phase_start_row = row_idx

        for task in phase.tasks:
            # Phase column (if applicable)
            if gantt.has_phases:
                cell = table.cell(row_idx, 0)
                set_cell_fill(cell, ICColors.WHITE)
                set_cell_border(cell, ICColors.BORDER_COLOR)
                # Phase name only on first row of phase
                if row_idx == phase_start_row and phase.name:
                    style_cell_text(cell, phase.name, bold=True,
                                   font_size=ICColors.FONT_SIZE_BODY)

                # Task name column
                cell = table.cell(row_idx, 1)
                set_cell_fill(cell, ICColors.WHITE)
                set_cell_border(cell, ICColors.BORDER_COLOR)
                style_cell_text(cell, task.name, font_size=ICColors.FONT_SIZE_BODY)
            else:
                # Task name only
                cell = table.cell(row_idx, 0)
                set_cell_fill(cell, ICColors.WHITE)
                set_cell_border(cell, ICColors.BORDER_COLOR)
                style_cell_text(cell, task.name, font_size=ICColors.FONT_SIZE_BODY)

            # Time columns
            for i in range(num_time_cols):
                col = num_label_cols + i
                cell = table.cell(row_idx, col)
                set_cell_border(cell, ICColors.BORDER_COLOR)

                # Check if this column is in task duration
                if task.start <= i <= task.end:
                    if task.is_milestone:
                        set_cell_fill(cell, ICColors.MILESTONE_FILL)
                        text_color = ICColors.WHITE
                    else:
                        set_cell_fill(cell, ICColors.WORK_FILL)
                        text_color = ICColors.WHITE

                    # Show label in the first cell of the duration span
                    if i == task.start and task.label:
                        style_cell_text(cell, task.label, font_size=ICColors.FONT_SIZE_BODY,
                                       color=text_color, align='center')
                    else:
                        style_cell_text(cell, "", font_size=ICColors.FONT_SIZE_BODY)
                elif i in gantt.holidays:
                    set_cell_fill(cell, ICColors.HOLIDAY_FILL)
                    style_cell_text(cell, "", font_size=ICColors.FONT_SIZE_BODY)
                else:
                    set_cell_fill(cell, ICColors.WHITE)
                    style_cell_text(cell, "", font_size=ICColors.FONT_SIZE_BODY)

            row_idx += 1

        # Merge phase cells if multiple tasks in phase
        if gantt.has_phases and len(phase.tasks) > 1:
            start_cell = table.cell(phase_start_row, 0)
            end_cell = table.cell(row_idx - 1, 0)
            try:
                start_cell.merge(end_cell)
            except:
                pass  # Merge may fail if already merged

    return table_shape


# =============================================================================
# TIMELINE ENTRY CONVERSION
# =============================================================================

def build_gantt_data_from_timeline_entries(timeline: list, title: str = "Timeline") -> GanttData:
    """Convert layout plan timeline format to GanttData structure.

    Timeline entries from layout plan look like:
    [
        {"date": "Week 1", "activity": "Kickoff meeting", "phase": "Discovery"},
        {"date": "Week 2-4", "activity": "Research", "phase": "Discovery", "milestone": True},
        ...
    ]

    Args:
        timeline: List of timeline entry dicts from layout plan
        title: Title for the Gantt chart

    Returns:
        GanttData structure ready for rendering
    """
    if not timeline:
        return GanttData(title=title)

    gantt = GanttData(title=title)

    # Analyze entries to determine week range and phases
    phases_dict: dict = {}  # phase_name -> Phase
    all_weeks = []

    for entry in timeline:
        date_str = entry.get('date', '') or entry.get('time', '') or ''
        activity = entry.get('activity', '') or entry.get('description', '') or entry.get('title', '')
        phase_name = entry.get('phase', '')
        is_milestone = entry.get('milestone', False)
        label = entry.get('label', '')

        # Parse date/week range
        start_week, end_week = _parse_week_range(date_str)
        if start_week is not None:
            all_weeks.extend([start_week, end_week])

            # Create task
            task = Task(
                name=activity,
                start=start_week,
                end=end_week,
                is_milestone=is_milestone,
                label=label
            )

            # Add to phase
            if phase_name not in phases_dict:
                phases_dict[phase_name] = Phase(name=phase_name)
            phases_dict[phase_name].add_task(task)

    # Set up columns based on week range
    if all_weeks:
        min_week = min(all_weeks)
        max_week = max(all_weeks)
        # Create column headers
        gantt.columns = [f"WEEK {w+1}" for w in range(min_week, max_week + 1)]
        # Normalize task indices to 0-based
        offset = min_week
        for phase in phases_dict.values():
            for task in phase.tasks:
                task.start -= offset
                task.end -= offset
            gantt.phases.append(phase)

    gantt.is_week_based = True
    return gantt


def _parse_week_range(date_str: str) -> tuple:
    """Parse a week string like 'Week 1', 'Week 2-4', 'W3-W5' into (start, end) indices.

    Returns (None, None) if parsing fails.
    """
    import re

    if not date_str:
        return (None, None)

    date_str = date_str.strip().lower()

    # Try "week N" or "w N"
    single = re.match(r'(?:week|w)\s*(\d+)', date_str)
    if single and '-' not in date_str:
        week = int(single.group(1)) - 1  # 0-indexed
        return (week, week)

    # Try "week N-M" or "week N - week M" or "w N-M"
    range_match = re.match(r'(?:week|w)\s*(\d+)\s*-\s*(?:week|w)?\s*(\d+)', date_str)
    if range_match:
        start = int(range_match.group(1)) - 1
        end = int(range_match.group(2)) - 1
        return (start, end)

    # Try simple "N-M"
    simple_range = re.match(r'(\d+)\s*-\s*(\d+)', date_str)
    if simple_range:
        start = int(simple_range.group(1)) - 1
        end = int(simple_range.group(2)) - 1
        return (start, end)

    return (None, None)


def should_render_as_gantt(timeline: list) -> bool:
    """Determine if a timeline should be rendered as a Gantt chart.

    Returns True if:
    - 4 or more entries
    - Entries have week/date ranges (not just labels)
    - At least some entries have phase groupings

    Returns False for simple timelines that work better as visual markers.
    """
    if not timeline or len(timeline) < 4:
        return False

    # Check if entries have parseable dates/weeks
    parseable_count = 0
    has_phases = False

    for entry in timeline:
        date_str = entry.get('date', '') or entry.get('time', '') or ''
        start, end = _parse_week_range(date_str)
        if start is not None:
            parseable_count += 1
        if entry.get('phase'):
            has_phases = True

    # Need at least 60% of entries to have parseable dates
    return parseable_count >= len(timeline) * 0.6
