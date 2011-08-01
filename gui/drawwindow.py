# -*- coding: utf-8 -*-
#
# This file is part of MyPaint.
# Copyright (C) 2007-2008 by Martin Renold <martinxyz@gmx.ch>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""
This is the main drawing window, containing menu actions.
Painting is done in tileddrawwidget.py.
"""

MYPAINT_VERSION="0.9.1+git"

import os, math, time
from gettext import gettext as _

import gtk, gobject
from gtk import gdk, keysyms

import colorselectionwindow, historypopup, stategroup, colorpicker, windowing, layout
import dialogs
from lib import helpers
import stock

import xml.etree.ElementTree as ET

# palette support
from lib.scratchpad_palette import GimpPalette, hatch_squiggle, squiggle, draw_palette

# TODO: put in a helper file?
def with_wait_cursor(func):
    """python decorator that adds a wait cursor around a function"""
    def wrapper(self, *args, **kwargs):
        toplevels = [t for t in gtk.window_list_toplevels()
                     if t.window is not None]
        for toplevel in toplevels:
            toplevel.window.set_cursor(gdk.Cursor(gdk.WATCH))
            toplevel.set_sensitive(False)
        self.app.doc.tdw.grab_add()
        try:
            func(self, *args, **kwargs)
            # gtk main loop may be called in here...
        finally:
            for toplevel in toplevels:
                toplevel.set_sensitive(True)
                # ... which is why we need this check:
                if toplevel.window is not None:
                    toplevel.window.set_cursor(None)
            self.app.doc.tdw.grab_remove()
    return wrapper

def button_press_cb_abstraction(drawwindow, win, event, doc):
    #print event.device, event.button

    ## Ignore accidentals
    # Single button-presses only, not 2ble/3ple
    if event.type != gdk.BUTTON_PRESS:
        # ignore the extra double-click event
        return False

    if event.button != 1:
        # check whether we are painting (accidental)
        if event.state & gdk.BUTTON1_MASK:
            # Do not allow dragging in the middle of
            # painting. This often happens by accident with wacom
            # tablet's stylus button.
            #
            # However we allow dragging if the user's pressure is
            # still below the click threshold.  This is because
            # some tablet PCs are not able to produce a
            # middle-mouse click without reporting pressure.
            # https://gna.org/bugs/index.php?15907
            return False

    # Pick a suitable config option
    ctrl = event.state & gdk.CONTROL_MASK
    alt  = event.state & gdk.MOD1_MASK
    shift = event.state & gdk.SHIFT_MASK
    if shift:
        modifier_str = "_shift"
    elif alt or ctrl:
        modifier_str = "_ctrl"
    else:
        modifier_str = ""
    prefs_name = "input.button%d%s_action" % (event.button, modifier_str)
    action_name = drawwindow.app.preferences.get(prefs_name, "no_action")

    # No-ops
    if action_name == 'no_action':
        return True  # We handled it by doing nothing

    # Straight line
    # Really belongs in the tdw, but this is the only object with access
    # to the application preferences.
    if action_name == 'straight_line':
        doc.tdw.straight_line_from_last_pos(is_sequence=False)
        return True
    if action_name == 'straight_line_sequence':
        doc.tdw.straight_line_from_last_pos(is_sequence=True)
        return True

    # View control
    if action_name.endswith("_canvas"):
        dragfunc = None
        if action_name == "pan_canvas":
            dragfunc = doc.dragfunc_translate
        elif action_name == "zoom_canvas":
            dragfunc = doc.dragfunc_zoom
        elif action_name == "rotate_canvas":
            dragfunc = doc.dragfunc_rotate
        if dragfunc is not None:
            doc.tdw.start_drag(dragfunc)
            return True
        return False

    # Application menu
    if action_name == 'popup_menu':
        drawwindow.show_popupmenu(event=event)
        return True

    if action_name in drawwindow.popup_states:
        state = drawwindow.popup_states[action_name]
        state.activate(event)
        return True

    # Dispatch regular GTK events.
    for ag in drawwindow.action_group, doc.action_group:
        action = ag.get_action(action_name)
        if action is not None:
            action.activate()
            return True

def button_release_cb_abstraction(win, event, doc):
    #print event.device, event.button
    tdw = doc.tdw
    if tdw.dragfunc is not None:
        tdw.stop_drag(doc.dragfunc_translate)
        tdw.stop_drag(doc.dragfunc_rotate)
        tdw.stop_drag(doc.dragfunc_zoom)
    return False

class Window (windowing.MainWindow, layout.MainWindow):

    def __init__(self, app):
        windowing.MainWindow.__init__(self, app)
        self.app = app

        # Window handling
        self._updating_toggled_item = False
        self._show_subwindows = True
        self.is_fullscreen = False

        # Enable drag & drop
        self.drag_dest_set(gtk.DEST_DEFAULT_MOTION |
                            gtk.DEST_DEFAULT_HIGHLIGHT |
                            gtk.DEST_DEFAULT_DROP,
                            [("text/uri-list", 0, 1),
                             ("application/x-color", 0, 2)],
                            gtk.gdk.ACTION_DEFAULT|gtk.gdk.ACTION_COPY)

        # Connect events
        self.connect('delete-event', self.quit_cb)
        self.connect('key-press-event', self.key_press_event_cb_before)
        self.connect('key-release-event', self.key_release_event_cb_before)
        self.connect_after('key-press-event', self.key_press_event_cb_after)
        self.connect_after('key-release-event', self.key_release_event_cb_after)
        self.connect("drag-data-received", self.drag_data_received)
        self.connect("window-state-event", self.window_state_event_cb)

        self.app.filehandler.current_file_observers.append(self.update_title)

        self.init_actions()

        lm = app.layout_manager
        layout.MainWindow.__init__(self, lm)
        self.main_widget.connect("button-press-event", self.button_press_cb)
        self.main_widget.connect("button-release-event",self.button_release_cb)
        self.main_widget.connect("scroll-event", self.scroll_cb)

        kbm = self.app.kbm
        kbm.add_extra_key('Menu', 'ShowPopupMenu')
        kbm.add_extra_key('Tab', 'ToggleSubwindows')

        self.init_stategroups()

    #XXX: Compatability
    def get_doc(self):
        print "DeprecationWarning: Use app.doc instead"
        return self.app.doc
    def get_tdw(self):
        print "DeprecationWarning: Use app.doc.tdw instead"
        return self.app.doc.tdw
    tdw, doc = property(get_tdw), property(get_doc)

    def init_actions(self):
        actions = [
            # name, stock id, label, accelerator, tooltip, callback
            ('FileMenu',    None, _('File')),
            ('Quit',         gtk.STOCK_QUIT, _('Quit'), '<control>q', None, self.quit_cb),
            ('FrameToggle',  None, _('Toggle Document Frame'), None, None, self.toggle_frame_cb),

            ('EditMenu',        None, _('Edit')),

            ('ColorMenu',    None, _('Color')),
            ('ColorPickerPopup',    gtk.STOCK_COLOR_PICKER, _('Pick Color'), 'r', None, self.popup_cb),
            ('ColorHistoryPopup',  None, _('Color History'), 'x', None, self.popup_cb),
            ('ColorChangerPopup', None, _('Color Changer'), 'v', None, self.popup_cb),
            ('ColorRingPopup',  None, _('Color Ring'), None, None, self.popup_cb),

            ('ContextMenu',  None, _('Brushkeys')),
            ('ContextHelp',  gtk.STOCK_HELP, _('Help!'), None, None, self.show_infodialog_cb),

            ('LayerMenu',    None, _('Layers')),

            # Scratchpad menu items
            ('ScratchMenu',    None, _('Scratchpad')),
            ('ScratchNew',  gtk.STOCK_NEW, _('New scratchpad'), '', None, self.new_scratchpad_cb),
            ('ScratchLoad',  gtk.STOCK_OPEN, _('Load into scratchpad'), '', None, self.load_scratchpad_cb),
            ('ScratchSaveNow',  gtk.STOCK_SAVE, _('Save Scratchpad Now'), '', None, self.save_current_scratchpad_cb),
            ('ScratchSaveAs',  gtk.STOCK_SAVE_AS, _('Save Scratchpad As...'), '', None, self.save_as_scratchpad_cb),
            ('ScratchRevert',  gtk.STOCK_UNDO, _('Revert scratchpad'), '', None, self.revert_current_scratchpad_cb),
            ('ScratchSaveAsDefault',  None, _('Save Scratchpad As Default'), None, None, self.save_scratchpad_as_default_cb),
            ('ScratchClearDefault',  None, _('Clear the Default Scratchpad'), None, None, self.clear_default_scratchpad_cb),
            ('ScratchLoadPalette',  None, _('Draw a palette in the current Scratchpad'), None, None, self.draw_palette_cb),
            ('ScratchPaletteOptions',    None, _('Draw a palette...')),
            ('ScratchDrawSatPalette',  None, _('Draw a saturation palette of current color'), None, None, self.draw_sat_spectrum_cb),
            ('ScratchCopyBackground',  None, _('Match scratchpad bg to canvas bg'), None, None, self.scratchpad_copy_background_cb),

            ('BrushMenu',    None, _('Brush')),
            ('ImportBrushPack',       gtk.STOCK_OPEN, _('Import brush package...'), '', None, self.import_brush_pack_cb),

            ('HelpMenu',   None, _('Help')),
            ('Docu', gtk.STOCK_INFO, _('Where is the Documentation?'), None, None, self.show_infodialog_cb),
            ('ShortcutHelp',  gtk.STOCK_INFO, _('Change the Keyboard Shortcuts?'), None, None, self.show_infodialog_cb),
            ('About', gtk.STOCK_ABOUT, _('About MyPaint'), None, None, self.about_cb),

            ('DebugMenu',    None, _('Debug')),
            ('PrintMemoryLeak',  None, _('Print Memory Leak Info to Console (Slow!)'), None, None, self.print_memory_leak_cb),
            ('RunGarbageCollector',  None, _('Run Garbage Collector Now'), None, None, self.run_garbage_collector_cb),
            ('StartProfiling',  gtk.STOCK_EXECUTE, _('Start/Stop Python Profiling (cProfile)'), None, None, self.start_profiling_cb),
            ('GtkInputDialog',  None, _('GTK input device dialog'), None, None, self.gtk_input_dialog_cb),


            ('ViewMenu', None, _('View')),
            ('ShowPopupMenu',    None, _('Popup Menu'), 'Menu', None, self.popupmenu_show_cb),
            ('Fullscreen',   gtk.STOCK_FULLSCREEN, _('Fullscreen'), 'F11', None, self.fullscreen_cb),
            ('ViewHelp',  gtk.STOCK_HELP, _('Help'), None, None, self.show_infodialog_cb),
            ]
        ag = self.action_group = gtk.ActionGroup('WindowActions')
        ag.add_actions(actions)

        # Toggle actions
        toggle_actions = [
            ('PreferencesWindow', gtk.STOCK_PREFERENCES,
                    _('Preferences'), None, None, self.toggle_window_cb),
            ('InputTestWindow',  None,
                    _('Test input devices'), None, None, self.toggle_window_cb),
            ('FrameWindow',  None,
                    _('Document Frame...'), None, None, self.toggle_window_cb),
            ('LayersWindow', stock.TOOL_LAYERS,
                    None, None, _("Toggle the Layers list"),
                    self.toggle_window_cb),
            ('BackgroundWindow', gtk.STOCK_PAGE_SETUP,
                    _('Background'), None, None, self.toggle_window_cb),
            ('BrushSelectionWindow', stock.TOOL_BRUSH,
                    None, None, _("Toggle the Brush selector"),
                    self.toggle_window_cb),
            ('BrushSettingsWindow', gtk.STOCK_PROPERTIES,
                    _('Brush Editor'), '<control>b', None,
                    self.toggle_window_cb),
            ('ColorSelectionWindow', stock.TOOL_COLOR_SELECTOR,
                    None, None, _("Toggle the Colour Triangle"),
                    self.toggle_window_cb),
            ('ColorSamplerWindow', stock.TOOL_COLOR_SAMPLER,
                    None, None, _("Toggle the advanced Colour Sampler"),
                    self.toggle_window_cb),
            ('ScratchWindow',  stock.TOOL_SCRATCHPAD, 
                    None, None, _('Toggle the scratchpad'),
                    self.toggle_window_cb),
            ]
        ag.add_toggle_actions(toggle_actions)

        # Reflect changes from other places (like tools' close buttons) into
        # the proxys' visible states.
        lm = self.app.layout_manager
        lm.tool_visibility_observers.append(self.update_toggled_item_visibility)
        lm.subwindow_visibility_observers.append(self.update_subwindow_visibility)

        # Initial toggle state
        for spec in toggle_actions:
            name = spec[0]
            action = ag.get_action(name)
            role = name[0].lower() + name[1:]
            visible = not lm.get_window_hidden_by_role(role)
            # The sidebar machinery won't be up yet, so reveal windows that
            # should be initially visible only in an idle handler
            gobject.idle_add(action.set_active, visible)

        # More toggle actions - ones which don't control windows.
        toggle_actions = [
            ('ToggleToolbar', None, _('Toolbar'), None,
                    _("Show toolbar"), self.toggle_toolbar_cb,
                    self.get_show_toolbar()),
            ('ToggleSubwindows', None, _('Subwindows'), 'Tab',
                    _("Show subwindows"), self.toggle_subwindows_cb,
                    self.get_show_subwindows()),
            ]
        ag.add_toggle_actions(toggle_actions)

        # Keyboard handling
        for action in self.action_group.list_actions():
            self.app.kbm.takeover_action(action)
        self.app.ui_manager.insert_action_group(ag, -1)

    def init_stategroups(self):
        sg = stategroup.StateGroup()
        p2s = sg.create_popup_state
        changer = p2s(colorselectionwindow.ColorChangerPopup(self.app))
        ring = p2s(colorselectionwindow.ColorRingPopup(self.app))
        hist = p2s(historypopup.HistoryPopup(self.app, self.app.doc.model))
        pick = self.colorpick_state = p2s(colorpicker.ColorPicker(self.app, self.app.doc.model))

        self.popup_states = {
            'ColorChangerPopup': changer,
            'ColorRingPopup': ring,
            'ColorHistoryPopup': hist,
            'ColorPickerPopup': pick,
            }
        changer.next_state = ring
        ring.next_state = changer
        changer.autoleave_timeout = None
        ring.autoleave_timeout = None

        pick.max_key_hit_duration = 0.0
        pick.autoleave_timeout = None

        hist.autoleave_timeout = 0.600
        self.history_popup_state = hist

    def init_main_widget(self):  # override
        self.main_widget = self.app.doc.tdw

    def init_menubar(self):   # override
        # Load Menubar, duplicate into self.popupmenu
        menupath = os.path.join(self.app.datapath, 'gui/menu.xml')
        menubar_xml = open(menupath).read()
        self.app.ui_manager.add_ui_from_string(menubar_xml)
        self._init_popupmenu(menubar_xml)
        self.menubar = self.app.ui_manager.get_widget('/Menubar')

    def init_toolbar(self):
        toolbarpath = os.path.join(self.app.datapath, 'gui/toolbar.xml')
        toolbarbar_xml = open(toolbarpath).read()
        self.app.ui_manager.add_ui_from_string(toolbarbar_xml)
        self.toolbar = self.app.ui_manager.get_widget('/toolbar1')
        if not self.get_show_toolbar():
            gobject.idle_add(self.toolbar.hide)


    def _init_popupmenu(self, xml):
        """
        Hopefully temporary hack for converting UIManager XML describing the
        main menubar into a rebindable popup menu. UIManager by itself doesn't
        let you do this, by design, but we need a bigger menu than the little
        things it allows you to build.
        """
        ui_elt = ET.fromstring(xml)
        rootmenu_elt = ui_elt.find("menubar")
        rootmenu_elt.attrib["name"] = "PopupMenu"
        ## XML-style menu jiggling. No need for this really though.
        #for menu_elt in rootmenu_elt.findall("menu"):
        #    for item_elt in menu_elt.findall("menuitem"):
        #        if item_elt.attrib.get("action", "") == "ShowPopupMenu":
        #            menu_elt.remove(item_elt)
        ## Maybe shift a small number of frequently-used items to the top?
        xml = ET.tostring(ui_elt)
        self.app.ui_manager.add_ui_from_string(xml)
        tmp_menubar = self.app.ui_manager.get_widget('/PopupMenu')
        self.popupmenu = gtk.Menu()
        for item in tmp_menubar.get_children():
            tmp_menubar.remove(item)
            self.popupmenu.append(item)
        self.popupmenu.attach_to_widget(self.app.doc.tdw, None)
        #self.popupmenu.set_title("MyPaint")
        #self.popupmenu.set_take_focus(True)
        self.popupmenu.connect("selection-done", self.popupmenu_done_cb)
        self.popupmenu.connect("deactivate", self.popupmenu_done_cb)
        self.popupmenu.connect("cancel", self.popupmenu_done_cb)
        self.popupmenu_last_active = None


    def update_title(self, filename):
        if filename:
            self.set_title("MyPaint - %s" % os.path.basename(filename))
        else:
            self.set_title("MyPaint")

    # INPUT EVENT HANDLING
    def drag_data_received(self, widget, context, x, y, selection, info, t):
        if info == 1:
            if selection.data:
                uri = selection.data.split("\r\n")[0]
                fn = helpers.uri2filename(uri)
                if os.path.exists(fn):
                    if self.app.filehandler.confirm_destructive_action():
                        self.app.filehandler.open_file(fn)
        elif info == 2: # color
            color = [((ord(selection.data[v]) | (ord(selection.data[v+1]) << 8)) / 65535.0)  for v in range(0,8,2)]
            self.app.brush.set_color_rgb(color[:3])
            self.app.ch.push_color(self.app.brush.get_color_hsv())
            # Don't popup the color history for now, as I haven't managed to get it to cooperate.

    def print_memory_leak_cb(self, action):
        helpers.record_memory_leak_status(print_diff = True)

    def run_garbage_collector_cb(self, action):
        helpers.run_garbage_collector()

    def start_profiling_cb(self, action):
        if getattr(self, 'profiler_active', False):
            self.profiler_active = False
            return

        def doit():
            import cProfile
            profile = cProfile.Profile()

            self.profiler_active = True
            print '--- GUI Profiling starts ---'
            while self.profiler_active:
                profile.runcall(gtk.main_iteration, False)
                if not gtk.events_pending():
                    time.sleep(0.050) # ugly trick to remove "user does nothing" from profile
            print '--- GUI Profiling ends ---'

            profile.dump_stats('profile_fromgui.pstats')
            #print 'profile written to mypaint_profile.pstats'
            os.system('gprof2dot.py -f pstats profile_fromgui.pstats | dot -Tpng -o profile_fromgui.png && feh profile_fromgui.png &')

        gobject.idle_add(doit)

    def gtk_input_dialog_cb(self, action):
        d = gtk.InputDialog()
        d.show()

    def key_press_event_cb_before(self, win, event):
        key = event.keyval
        ctrl = event.state & gdk.CONTROL_MASK
        shift = event.state & gdk.SHIFT_MASK
        alt = event.state & gdk.MOD1_MASK
        #ANY_MODIFIER = gdk.SHIFT_MASK | gdk.MOD1_MASK | gdk.CONTROL_MASK
        #if event.state & ANY_MODIFIER:
        #    # allow user shortcuts with modifiers
        #    return False

        # This may need a stateful flag
        if self.app.scratchpad_doc.tdw.has_pointer:
            thisdoc = self.app.scratchpad_doc
            # Stop dragging on the main window
            self.app.doc.tdw.dragfunc = None
        else:
            thisdoc = self.app.doc
            # Stop dragging on the other window
            self.app.scratchpad_doc.tdw.dragfunc = None
        if key == keysyms.space:
            if shift:
                 thisdoc.tdw.start_drag(thisdoc.dragfunc_rotate)
            elif ctrl:
                thisdoc.tdw.start_drag(thisdoc.dragfunc_zoom)
            elif alt:
                thisdoc.tdw.start_drag(thisdoc.dragfunc_frame)
            else:
                thisdoc.tdw.start_drag(thisdoc.dragfunc_translate)
        else: return False
        return True

    def key_release_event_cb_before(self, win, event):
        if self.app.scratchpad_doc.tdw.has_pointer:
            thisdoc = self.app.scratchpad_doc
        else:
            thisdoc = self.app.doc
        if event.keyval == keysyms.space:
            thisdoc.tdw.stop_drag(thisdoc.dragfunc_translate)
            thisdoc.tdw.stop_drag(thisdoc.dragfunc_rotate)
            thisdoc.tdw.stop_drag(thisdoc.dragfunc_zoom)
            thisdoc.tdw.stop_drag(thisdoc.dragfunc_frame)
            return True
        return False

    def key_press_event_cb_after(self, win, event):
        key = event.keyval
        if self.is_fullscreen and key == keysyms.Escape:
            self.fullscreen_cb()
        else:
            return False
        return True

    def key_release_event_cb_after(self, win, event):
        return False

    def button_press_cb(self, win, event):
        return button_press_cb_abstraction(self, win, event, self.app.doc)

    def button_release_cb(self, win, event):
        return button_release_cb_abstraction(win, event, self.app.doc)

    def scroll_cb(self, win, event):
        d = event.direction
        if d == gdk.SCROLL_UP:
            if event.state & gdk.SHIFT_MASK:
                self.app.doc.rotate('RotateLeft')
            else:
                self.app.doc.zoom('ZoomIn')
        elif d == gdk.SCROLL_DOWN:
            if event.state & gdk.SHIFT_MASK:
                self.app.doc.rotate('RotateRight')
            else:
                self.app.doc.zoom('ZoomOut')
        elif d == gdk.SCROLL_RIGHT:
            self.app.doc.rotate('RotateRight')
        elif d == gdk.SCROLL_LEFT:
            self.app.doc.rotate('RotateLeft')

    # WINDOW HANDLING
    def toggle_window_cb(self, action):
        if self._updating_toggled_item:
            return
        s = action.get_name()
        active = action.get_active()
        window_name = s[0].lower() + s[1:] # WindowName -> windowName
        # If it's a tool, get it to hide/show itself
        t = self.app.layout_manager.get_tool_by_role(window_name)
        if t is not None:
            t.set_hidden(not active)
            return
        # Otherwise, if it's a regular subwindow hide/show+present it.
        w = self.app.layout_manager.get_subwindow_by_role(window_name)
        if w is None:
            return
        onscreen = w.window is not None and w.window.is_visible()
        if active:
            if onscreen:
                return
            w.show_all()
            w.present()
        else:
            if not onscreen:
                return
            w.hide()

    def update_subwindow_visibility(self, window, active):
        # Responds to non-tool subwindows being hidden and shown
        role = window.get_role()
        self.update_toggled_item_visibility(role, active)

    def update_toggled_item_visibility(self, role, active, *a, **kw):
        # Responds to any item with a role being hidden or shown by
        # silently updating its ToggleAction to match.
        action_name = role[0].upper() + role[1:]
        action = self.action_group.get_action(action_name)
        if action is None:
            warn("Unable to find action %s" % action_name, RuntimeWarning, 1)
            return
        if action.get_active() != active:
            self._updating_toggled_item = True
            action.set_active(active)
            self._updating_toggled_item = False

    def popup_cb(self, action):
        state = self.popup_states[action.get_name()]
        state.activate(action)


    # Show Toolbar
    # Saved in the user prefs between sessions.
    # Controlled via its ToggleAction only.

    def set_show_toolbar(self, show_toolbar):
        """Programatically set the Show Toolbar option.
        """
        action = self.action_group.get_action("ToggleToolbar")
        if show_toolbar:
            if not action.get_active():
                action.set_active(True)
            self.app.preferences["ui.toolbar"] = True
        else:
            if action.get_active():
                action.set_active(False)
            self.app.preferences["ui.toolbar"] = False

    def get_show_toolbar(self):
        return self.app.preferences.get("ui.toolbar", True)

    def toggle_toolbar_cb(self, action):
        active = action.get_active()
        if active:
            self.toolbar.show_all()
        else:
            self.toolbar.hide()
        self.app.preferences["ui.toolbar"] = active


    # Show Subwindows
    # Not saved between sessions, defaults to on.
    # Controlled via its ToggleAction, and entering or leaving fullscreen mode
    # according to the setting of ui.hide_in_fullscreen in prefs.

    def set_show_subwindows(self, show_subwindows):
        """Programatically set the Show Subwindows option.
        """
        action = self.action_group.get_action("ToggleSubwindows")
        currently_showing = action.get_active()
        if show_subwindows != currently_showing:
            action.set_active(show_subwindows)
        self._show_subwindows = self._show_subwindows

    def get_show_subwindows(self):
        return self._show_subwindows

    def toggle_subwindows_cb(self, action):
        active = action.get_active()
        lm = self.app.layout_manager
        if active:
            lm.toggle_user_tools(on=True)
        else:
            lm.toggle_user_tools(on=False)
        self._show_subwindows = active


    # Fullscreen mode
    # This implementation requires an ICCCM and EWMH-compliant window manager
    # which supports the _NET_WM_STATE_FULLSCREEN hint. There are several
    # available.

    def fullscreen_cb(self, *junk):
        if not self.is_fullscreen:
            self.fullscreen()
        else:
            self.unfullscreen()

    def window_state_event_cb(self, widget, event):
        # Respond to changes of the fullscreen state only
        if not event.changed_mask & gdk.WINDOW_STATE_FULLSCREEN:
            return
        lm = self.app.layout_manager
        self.is_fullscreen = event.new_window_state & gdk.WINDOW_STATE_FULLSCREEN
        if self.is_fullscreen:
            # Subwindow hiding 
            if self.app.preferences.get("ui.hide_subwindows_in_fullscreen", True):
                self.set_show_subwindows(False)
                self._restore_subwindows_on_unfullscreen = True
            if self.app.preferences.get("ui.hide_menubar_in_fullscreen", True):
                self.menubar.hide()
                self._restore_menubar_on_unfullscreen = True
            if self.app.preferences.get("ui.hide_toolbar_in_fullscreen", True):
                self.toolbar.hide()
                self._restore_toolbar_on_unfullscreen = True
            # fix for fullscreen problem on Windows, https://gna.org/bugs/?15175
            # on X11/Metacity it also helps a bit against flickering during the switch
            while gtk.events_pending():
                gtk.main_iteration()
        else:
            while gtk.events_pending():
                gtk.main_iteration()
            if getattr(self, "_restore_menubar_on_unfullscreen", False):
                self.menubar.show()
                del self._restore_menubar_on_unfullscreen
            if getattr(self, "_restore_toolbar_on_unfullscreen", False):
                if self.get_show_toolbar():
                    self.toolbar.show()
                del self._restore_toolbar_on_unfullscreen
            if getattr(self, "_restore_subwindows_on_unfullscreen", False):
                self.set_show_subwindows(True)
                del self._restore_subwindows_on_unfullscreen

    def popupmenu_show_cb(self, action):
        self.show_popupmenu()

    def show_popupmenu(self, event=None):
        self.menubar.set_sensitive(False)   # excessive feedback?
        button = 1
        time = 0
        if event is not None:
            if event.type == gdk.BUTTON_PRESS:
                button = event.button
                time = event.time
        self.popupmenu.popup(None, None, None, button, time)
        if event is None:
            # We're responding to an Action, most probably the menu key.
            # Open out the last highlighted menu to speed key navigation up.
            if self.popupmenu_last_active is None:
                self.popupmenu.select_first(True) # one less keypress
            else:
                self.popupmenu.select_item(self.popupmenu_last_active)

    def popupmenu_done_cb(self, *a, **kw):
        # Not sure if we need to bother with this level of feedback,
        # but it actaully looks quite nice to see one menu taking over
        # the other. Makes it clear that the popups are the same thing as
        # the full menu, maybe.
        self.menubar.set_sensitive(True)
        self.popupmenu_last_active = self.popupmenu.get_active()

    # BEGIN -- Scratchpad menu options
    def save_scratchpad_as_default_cb(self, action):
        self.app.filehandler.save_scratchpad(self.app.filehandler.get_scratchpad_default(), export = True)
    
    def clear_default_scratchpad_cb(self, action):
        self.app.filehandler.delete_default_scratchpad()

    # Unneeded since 'Save blank canvas' bug has been addressed.
    #def clear_autosave_scratchpad_cb(self, action):
    #    self.app.filehandler.delete_autosave_scratchpad()

    def new_scratchpad_cb(self, action):
        if os.path.isfile(self.app.filehandler.get_scratchpad_default()):
            self.app.filehandler.open_scratchpad(self.app.filehandler.get_scratchpad_default())
        else:
            self.app.scratchpad_doc.model.clear()
            # With no default - adopt the currently chosen background
            bg = self.app.doc.model.background
            if self.app.scratchpad_doc:
                self.app.scratchpad_doc.model.set_background(bg)
            
        self.app.scratchpad_filename = self.app.preferences['scratchpad.last_opened'] = self.app.filehandler.get_scratchpad_autosave()

    def load_scratchpad_cb(self, action):
        if self.app.scratchpad_filename:
            self.save_current_scratchpad_cb(action)
            current_pad = self.app.scratchpad_filename
        else:
            current_pad = self.app.filehandler.get_scratchpad_autosave()
        self.app.filehandler.open_scratchpad_dialog()
        # Check to see if a file has been opened outside of the scratchpad directory
        if not os.path.abspath(self.app.scratchpad_filename).startswith(os.path.abspath(self.app.filehandler.get_scratchpad_prefix())):
            # file is NOT within the scratchpad directory - load copy as current scratchpad
            self.app.scratchpad_filename = self.app.preferences['scratchpad.last_opened'] = current_pad

    def save_as_scratchpad_cb(self, action):
        self.app.filehandler.save_scratchpad_as_dialog()

    def revert_current_scratchpad_cb(self, action):
        if os.path.isfile(self.app.scratchpad_filename):                                                             
            self.app.filehandler.open_scratchpad(self.app.scratchpad_filename)
            print "Reverted to %s" % self.app.scratchpad_filename
        else:
            print "No file to revert to yet."
    
    def save_current_scratchpad_cb(self, action):
        self.app.filehandler.save_scratchpad(self.app.scratchpad_filename)

    def scratchpad_copy_background_cb(self, action):
        bg = self.app.doc.model.background
        if self.app.scratchpad_doc:
            self.app.scratchpad_doc.model.set_background(bg)

    def draw_palette_cb(self, action):
        # test functionality:
        file_filters = [
        (_("Gimp Palette Format"), ("*.gpl",)),
        (_("All Files"), ("*.*",)),
        ]
        gimp_path = os.path.join(self.app.filehandler.get_gimp_prefix(), "palettes")
        dialog = self.app.filehandler.get_open_dialog(start_in_folder=gimp_path,
                                                  file_filters = file_filters)
<<<<<<< HEAD
        try:
=======
        try:                                                                                                         
>>>>>>> 1433136bfb115424ccf7ad12e970abee36fa991b
            if dialog.run() == gtk.RESPONSE_OK:
                dialog.hide()
                filename = dialog.get_filename().decode('utf-8')
                if filename:
                    #filename = "/home/ben/.gimp-2.6/palettes/Nature_Grass.gpl" # TEMP HACK TO TEST
                    g = GimpPalette(filename)
                    grid_size = 30.0
                    column_limit = 7
                    # IGNORE Gimp Palette 'columns'?
                    if g.columns != 0:
                        column_limit = g.columns   # use the value for columns in the palette
                    draw_palette(self.app, g, self.app.scratchpad_doc, columns=column_limit, grid_size=grid_size, swatch_method=hatch_squiggle, scale = 25.0)
        finally:
            dialog.destroy()

    def draw_sat_spectrum_cb(self, action):
        g = GimpPalette()
        hsv = self.app.brush.get_color_hsv()
        g.append_sat_spectrum(hsv)
        grid_size = 30.0
        off_x = off_y = grid_size / 2.0
        column_limit = 8
        draw_palette(self.app, g, self.app.scratchpad_doc, columns=column_limit, grid_size=grid_size)

    # END -- Scratchpad menu options

    def quit_cb(self, *junk):
        self.app.doc.model.split_stroke()
        self.app.save_gui_config() # FIXME: should do this periodically, not only on quit

        if not self.app.filehandler.confirm_destructive_action(title=_('Quit'), question=_('Really Quit?')):
            return True

        gtk.main_quit()
        return False

    def toggle_frame_cb(self, action):
        enabled = self.app.doc.model.frame_enabled
        self.app.doc.model.set_frame_enabled(not enabled)

    def import_brush_pack_cb(self, *junk):
        format_id, filename = dialogs.open_dialog(_("Import brush package..."), self,
                                 [(_("MyPaint brush package (*.zip)"), "*.zip")])
        if filename:
            self.app.brushmanager.import_brushpack(filename,  self)

    # INFORMATION
    # TODO: Move into dialogs.py?
    def about_cb(self, action):
        d = gtk.AboutDialog()
        d.set_transient_for(self)
        d.set_program_name("MyPaint")
        d.set_version(MYPAINT_VERSION)
        d.set_copyright(_("Copyright (C) 2005-2010\nMartin Renold and the MyPaint Development Team"))
        d.set_website("http://mypaint.info/")
        d.set_logo(self.app.pixmaps.mypaint_logo)
        d.set_license(
            _(u"This program is free software; you can redistribute it and/or modify "
              u"it under the terms of the GNU General Public License as published by "
              u"the Free Software Foundation; either version 2 of the License, or "
              u"(at your option) any later version.\n"
              u"\n"
              u"This program is distributed in the hope that it will be useful, "
              u"but WITHOUT ANY WARRANTY. See the COPYING file for more details.")
            )
        d.set_wrap_license(True)
        d.set_authors([
            # (in order of appearance)
            u"Martin Renold (%s)" % _('programming'),
            u"Artis Rozentāls (%s)" % _('brushes'),
            u"Yves Combe (%s)" % _('portability'),
            u"Popolon (%s)" % _('brushes, programming'),
            u"Clement Skau (%s)" % _('programming'),
            u"Marcelo 'Tanda' Cerviño (%s)" % _('patterns, brushes'),
            u"Jon Nordby (%s)" % _('programming'),
            u"Álinson Santos (%s)" % _('programming'),
            u"Tumagonx (%s)" % _('portability'),
            u"Ilya Portnov (%s)" % _('programming'),
            u"David Revoy (%s)" % _('brushes'),
            u"Ramón Miranda (%s)" % _('brushes, patterns'),
            u"Enrico Guarnieri 'Ico_dY' (%s)" % _('brushes'),
            u"Jonas Wagner (%s)" % _('programming'),
            u"Luka Čehovin (%s)" % _('programming'),
            u"Andrew Chadwick (%s)" % _('programming'),
            u"Till Hartmann (%s)" % _('programming'),
            u"Nicola Lunghi (%s)" % _('patterns'),
            u"Toni Kasurinen (%s)" % _('brushes'),
            u"Сан Саныч (%s)" % _('patterns'),
            u'David Grundberg (%s)' % _('programming'),
            u"Krzysztof Pasek (%s)" % _('programming'),
            ])
        d.set_artists([
            u'Sebastian Kraft (%s)' % _('desktop icon'),
            ])
        # list all translators, not only those of the current language
        d.set_translator_credits(
            u'Ilya Portnov (ru)\n'
            u'Popolon (fr, zh_CN, ja)\n'
            u'Jon Nordby (nb)\n'
            u'Griatch (sv)\n'
            u'Tobias Jakobs (de)\n'
            u'Martin Tabačan (cs)\n'
            u'Tumagonx (id)\n'
            u'Manuel Quiñones (es)\n'
            u'Gergely Aradszki (hu)\n'
            u'Lamberto Tedaldi (it)\n'
            u'Dong-Jun Wu (zh_TW)\n'
            u'Luka Čehovin (sl)\n'
            u'Geuntak Jeong (ko)\n'
            u'Łukasz Lubojański (pl)\n'
            u'Daniel Korostil (uk)\n'
            u'Julian Aloofi (de)\n'
            u'Tor Egil Hoftun Kvæstad (nn_NO)\n'
            u'João S. O. Bueno (pt_BR)\n'
            u'David Grundberg (sv)\n'
            u'Elliott Sales de Andrade (en_CA)\n'
            )

        d.run()
        d.destroy()

    def show_infodialog_cb(self, action):
        text = {
        'ShortcutHelp':
                _("Move your mouse over a menu entry, then press the key to assign."),
        'ViewHelp':
                _("You can also drag the canvas with the mouse while holding the middle "
                "mouse button or spacebar. Or with the arrow keys."
                "\n\n"
                "In contrast to earlier versions, scrolling and zooming are harmless now and "
                "will not make you run out of memory. But you still require a lot of memory "
                "if you paint all over while fully zoomed out."),
        'ContextHelp':
                _("Brushkeys are used to quickly save/restore brush settings "
                 "using keyboard shortcuts. You can paint with one hand and "
                 "change brushes with the other without interruption."
                 "\n\n"
                 "There are 10 memory slots to hold brush settings.\n"
                 "They are anonymous brushes, which are not visible in the "
                 "brush selector list. But they are remembered even if you "
                 "quit."),
        'Docu':
                _("There is a tutorial available on the MyPaint homepage. It "
                 "explains some features which are hard to discover yourself."
                 "\n\n"
                 "Comments about the brush settings (opaque, hardness, etc.) and "
                 "inputs (pressure, speed, etc.) are available as tooltips. "
                 "Put your mouse over a label to see them. "
                 "\n"),
        }
        self.app.message_dialog(text[action.get_name()])
