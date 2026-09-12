from PySide6.QtCore import Qt

from fontplayground.ui.rail import STEP_SUBTITLES, STEP_TITLES, StepRail, done_title


def _rail(qtbot) -> StepRail:
    rail = StepRail()
    qtbot.addWidget(rail)
    rail.show()
    return rail


def test_titles_separators_and_initial_state(qtbot):
    rail = _rail(qtbot)
    assert [b.text().replace("&&", "&") for b in rail.buttons] == ["1  Pick fonts", "2  Check", "3  Forge & save"]
    assert rail.buttons[2].text() == "3  Forge && save"   # a lone '&' would be eaten as a shortcut marker
    assert [s.text() for s in rail.separators] == ["›", "›"]
    assert rail.step() == 0 and rail.buttons[0].isChecked()
    assert rail.subtitle() == STEP_SUBTITLES[0]
    assert [rail.is_reachable(i) for i in range(3)] == [True, False, False]
    assert not rail.buttons[1].isEnabled() and not rail.buttons[2].isEnabled()
    assert rail.group.exclusive()


def test_set_step_marks_completed_and_switches_subtitle(qtbot):
    rail = _rail(qtbot)
    rail.set_step(2)
    assert rail.step() == 2 and rail.buttons[2].isChecked() and not rail.buttons[0].isChecked()
    assert rail.buttons[0].text().startswith("✓ ") and rail.buttons[1].text().startswith("✓ ")
    assert rail.buttons[0].text() == done_title(STEP_TITLES[0]) == "✓  Pick fonts"
    assert rail.buttons[2].text() == "3  Forge && save"
    assert rail.buttons[0].property("done") is True and rail.buttons[2].property("done") is False
    assert all(rail.is_reachable(i) for i in range(3))   # the steps up to the current one become reachable
    assert rail.subtitle() == STEP_SUBTITLES[2] and rail.subtitle_stack.currentIndex() == 2
    rail.set_step(0)
    assert rail.buttons[0].text() == "1  Pick fonts" and rail.buttons[0].property("done") is False
    assert rail.buttons[0].isChecked() and rail.subtitle() == STEP_SUBTITLES[0]


def test_reachability_greys_and_blocks_clicks(qtbot):
    rail = _rail(qtbot)
    rail.set_reachable(1, True)
    assert rail.buttons[1].isEnabled() and not rail.buttons[2].isEnabled()
    with qtbot.assertNotEmitted(rail.stepClicked):
        qtbot.mouseClick(rail.buttons[2], Qt.MouseButton.LeftButton)
    assert rail.step() == 0 and rail.buttons[0].isChecked()
    rail.set_reachable(1, False)
    assert not rail.buttons[1].isEnabled()
    # the current step and completed steps cannot be made unreachable
    rail.set_step(1)
    rail.set_reachable(1, False)
    rail.set_reachable(0, False)
    assert rail.is_reachable(0) and rail.is_reachable(1)


def test_clicking_a_reachable_step_moves_and_emits(qtbot):
    rail = _rail(qtbot)
    rail.set_reachable(1, True)
    with qtbot.waitSignal(rail.stepClicked, timeout=1000) as blocker:
        qtbot.mouseClick(rail.buttons[1], Qt.MouseButton.LeftButton)
    assert blocker.args == [1]
    assert rail.step() == 1 and rail.buttons[1].isChecked() and rail.buttons[0].text().startswith("✓ ")
    # clicking the current step again still reports it, and keeps it checked (exclusive group)
    with qtbot.waitSignal(rail.stepClicked, timeout=1000) as blocker:
        qtbot.mouseClick(rail.buttons[1], Qt.MouseButton.LeftButton)
    assert blocker.args == [1] and rail.buttons[1].isChecked()


def test_overflow_menu_actions(qtbot):
    rail = _rail(qtbot)
    assert rail.menu_button.text() == "⋯" and rail.menu_button.menu() is rail.menu
    actions = [a for a in rail.menu.actions() if not a.isSeparator()]
    assert actions == [rail.rescan_action, rail.add_folder_action, rail.start_over_action, rail.open_settings_action]
    assert [a.text() for a in actions] == ["Rescan fonts", "Add folder…", "Start over", "Open settings folder"]
    with qtbot.waitSignal(rail.rescan_action.triggered, timeout=1000):
        rail.rescan_action.trigger()
    with qtbot.waitSignal(rail.start_over_action.triggered, timeout=1000):
        rail.start_over_action.trigger()
