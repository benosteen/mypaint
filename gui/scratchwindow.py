# This file is part of MyPaint.                                                                                      
# Copyright (C) 2011 by Ben O'Steen <bosteen@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import gtk
gdk = gtk.gdk
from gettext import gettext as _
import gobject
import pango

import tileddrawwidget, document

from drawwindow import button_press_cb_abstraction, button_release_cb_abstraction

import dialogs
import os

from hashlib import md5

def stock_button_generic(stock_id, b):
    img = gtk.Image()
    img.set_from_stock(stock_id, gtk.ICON_SIZE_MENU)
    b.add(img)
    return b

def stock_button(stock_id):
    b = gtk.Button()
    return stock_button_generic(stock_id, b)

class ToolWidget (gtk.VBox):

    tool_widget_title = _("Scratchpad")

    def __init__(self, app):
        gtk.VBox.__init__(self)
        self.app = app
        #self.set_size_request(200, 250)

        self.is_updating = False
        
        # Common controls
        load_button = self.load_button = stock_button(gtk.STOCK_OPEN)
        load_button.set_tooltip_text(_("Load Scratchpad"))
        save_as_button = self.save_as_button = stock_button(gtk.STOCK_SAVE_AS)
        save_as_button.set_tooltip_text(_("Save Scratchpad as..."))
        revert_button = self.revert_button = stock_button(gtk.STOCK_UNDO)
        revert_button.set_tooltip_text(_("Revert Scratchpad"))
        new_button = self.delete_button = stock_button(gtk.STOCK_NEW)
        new_button.set_tooltip_text(_("New Scratchpad"))

        load_button.connect('clicked', self.load_cb)
        save_as_button.connect('clicked', self.save_as_cb)
        revert_button.connect('clicked', self.revert_cb)
        new_button.connect('clicked', self.new_cb)

        buttons_hbox = gtk.HBox()
        buttons_hbox.pack_start(new_button)
        buttons_hbox.pack_start(load_button)
        buttons_hbox.pack_start(save_as_button)
        buttons_hbox.pack_start(revert_button)

        scratchpad_view = app.filehandler.scratchpad_doc.tdw

        self.connect("button-press-event", self.button_press_cb)
        self.connect("button-release-event",self.button_release_cb)
        self.connect("destroy-event", self.save_cb)
        self.connect("delete-event", self.save_cb)

        scratchpad_box = gtk.EventBox()
        scratchpad_box.add(scratchpad_view)

        self.pack_start(scratchpad_box)
        self.pack_start(buttons_hbox, expand=False)

        # Updates
        doc = app.filehandler.scratchpad_doc.model
        doc.doc_observers.append(self.update)

        # FIXME pull the scratchpad filename from preferences instead of this
        # self.app.filehandler.scratchpad_filename = self.scratchpad_filename = os.path.join(self.app.filehandler.get_scratchpad_prefix(), "scratchpad_default.ora")

        self.update(app.filehandler.scratchpad_doc)

    def new_cb(self, action):
        if os.path.isfile(self.app.filehandler.get_scratchpad_default()):
            self.app.filehandler.open_scratchpad(self.app.filehandler.get_scratchpad_default())
        else:
            self.app.filehandler.scratchpad_doc.model.clear()
        self.app.filehandler.scratchpad_filename = self.app.preferences['scratchpad.last_opened'] = self.app.filehandler.get_scratchpad_autosave()

    def revert_cb(self, action):
        # Load last scratchpad
        if os.path.isfile(self.app.filehandler.scratchpad_filename):
            self.app.filehandler.open_scratchpad(self.app.filehandler.scratchpad_filename)
            print "Reverted to %s" % self.app.filehandler.scratchpad_filename
        else:
            print "No file to revert to yet."

    def load_cb(self, action):
        if self.app.filehandler.scratchpad_filename:
            self.save_cb(action)
        self.app.filehandler.open_scratchpad_dialog()
        # Check to see if a file has been opened outside of the scratchpad directory
        if os.path.abspath(self.app.filehandler.scratchpad_filename).startswith(os.path.abspath(self.app.filehandler.get_scratchpad_prefix())):
            # file is within the scratchpad directory - no need to warn
            return

        # Doesn't start with the prefix
        d = gtk.Dialog(_("Scrachpad autosave warning"), self.app.drawWindow, gtk.DIALOG_MODAL)

        b = d.add_button(_("I understand"), gtk.RESPONSE_OK)
        b.set_image(gtk.image_new_from_stock(gtk.STOCK_APPLY, gtk.ICON_SIZE_BUTTON))
        b = d.add_button(_("_Save a copy"), gtk.RESPONSE_APPLY)
        b.set_image(gtk.image_new_from_stock(gtk.STOCK_SAVE, gtk.ICON_SIZE_BUTTON))

        d.set_has_separator(False)
        d.set_default_response(gtk.RESPONSE_APPLY)
        l = gtk.Label()
        l.set_markup("<b>Warning: the scratchpad automatically saves.</b>\n\nChanges made to the scratchpad will overwrite the file on disc\n As this file is not from the scratchpad directory, this may not be the behaviour you expect. \n\nIt is recommended that you save a copy into the scratchpad directory.")
        l.set_padding(10, 10)
        l.show()
        d.vbox.pack_start(l)
        response = d.run()
        d.destroy()
        if response == gtk.RESPONSE_APPLY:
            self.app.filehandler.scratchpad_filename = ""
            self.save_as_cb(None)
            return True
        return response == gtk.RESPONSE_OK

    def update(self, doc):
        if self.is_updating:
            return
        self.is_updating = True

    def save_as_cb(self, action):
        self.app.filehandler.save_scratchpad_as_dialog()

    def save_cb(self, action):
        print "Saving the scratchpad"
        self.app.filehandler.save_scratchpad(self.app.filehandler.scratchpad_filename)

    def button_press_cb(self, win, event):
        return button_press_cb_abstraction(self.app.drawWindow, win, event, self.app.filehandler.scratchpad_doc)

    def button_release_cb(self, win, event):
        return button_release_cb_abstraction(win, event, self.app.filehandler.scratchpad_doc)

