# -*- coding: utf-8 -*-

# Copyright 2015 Christian Wiwie <derwiwie@googlemail.com>

import glob
import gtk
import logging
import pango
import gobject
import bibtexparser

from zim.plugins import PluginClass, extends, WindowExtension
from zim.actions import action
from zim.gui.widgets import Dialog, Button, InputEntry, ScrolledWindow
from zim.plugins.base.imagegenerator import ImageGeneratorPlugin, ImageGeneratorClass
from zim.fs import File, TmpFile
from zim.config import data_file
from zim.templates import get_template
from zim.applications import Application, ApplicationError
from zim.objectmanager import ObjectManager, CustomObjectClass
from zim.gui.pageview import CustomObjectBin, POSITION_BEGIN, POSITION_END

logger = logging.getLogger('zim.plugins.insertbibtex')

OBJECT_TYPE_BIB = 'bibtexbib'
OBJECT_TYPE_REF = 'bibtexref'

class BibTexEditorPlugin(PluginClass):

	plugin_info = {
		'name': _('Insert BibTex'), # T: plugin name
		'description': _('''\
This plugin adds the 'Insert Table' dialog and allows
auto-formatting typographic characters.
'''), # T: plugin description
		'author': 'Christian Wiwie',
		'help': 'Plugins:Insert BibTex',
		'object_types': (OBJECT_TYPE_BIB, OBJECT_TYPE_REF),
	}
	
	unregisteredReferences = {}
	
	@classmethod
	def check_dependencies(klass):
		return True, []

	def __init__(self, config=None):
		PluginClass.__init__(self, config)

	def create_bib(self, attrib, text, ui=None):
		obj = BibTexBibObject(attrib, text, ui.mainwindow.pageview, ui) # XXX
		# register all the references not registered so far
		if BibTexEditorPlugin.unregisteredReferences.has_key(ui.mainwindow.pageview):
			if BibTexEditorPlugin.unregisteredReferences[ui.mainwindow.pageview].has_key(attrib['name']):
				for ref in BibTexEditorPlugin.unregisteredReferences[ui.mainwindow.pageview][attrib['name']]:
					obj.register_reference(ref)
				del BibTexEditorPlugin.unregisteredReferences[ui.mainwindow.pageview][attrib['name']]
		return obj
		
	def create_ref(self, attrib, text, ui=None):
		bibObj = None
		if BibTexBibObject.bibliographies.has_key(ui.mainwindow.pageview):
			for bib in BibTexBibObject.bibliographies[ui.mainwindow.pageview]:
				if bib._attrib['name'] == attrib['bibname']:
					bibObj = bib
		obj = BibTexRefObject(attrib, text, bibObj, ui.mainwindow.pageview, ui) # XXX
		# store the object such that we register it later at the bibliography
		if not BibTexBibObject.bibliographies.has_key(ui.mainwindow.pageview):
			if not BibTexEditorPlugin.unregisteredReferences.has_key(ui.mainwindow.pageview):
				BibTexEditorPlugin.unregisteredReferences[ui.mainwindow.pageview] = {}
			if not BibTexEditorPlugin.unregisteredReferences[ui.mainwindow.pageview].has_key(attrib['bibname']):
				BibTexEditorPlugin.unregisteredReferences[ui.mainwindow.pageview][attrib['bibname']] = []
			BibTexEditorPlugin.unregisteredReferences[ui.mainwindow.pageview][attrib['bibname']].append(obj)
		return obj


@extends('MainWindow')
class MainWindowExtension(WindowExtension):

	uimanager_xml = '''
	<ui>
	<menubar name='menubar'>
		<menu action='insert_menu'>
			<placeholder name='plugin_items'>
				<menuitem action='insert_bibtex_bib'/>
				<menuitem action='insert_bibtex_ref'/>
			</placeholder>
		</menu>
	</menubar>
	</ui>
	'''

	def __init__(self, plugin, window):
		WindowExtension.__init__(self, plugin, window)
		ObjectManager.register_object(OBJECT_TYPE_BIB, self.plugin.create_bib)
		ObjectManager.register_object(OBJECT_TYPE_REF, self.plugin.create_ref)

	def teardown(self):
		ObjectManager.unregister_object(OBJECT_TYPE_BIB)
		ObjectManager.unregister_object(OBJECT_TYPE_REF)

	@action(_('Bibliograph_y...')) # T: menu item
	def insert_bibtex_bib(self):
		dialog = InsertBibTexBibDialog(self.window, self.window.pageview)
		lang = dialog.run()
		if not lang:
			return # dialog cancelled
		else:
			obj = BibTexBibObject({'type': OBJECT_TYPE_BIB, 'name': dialog.bibName, 'path': dialog.bibPath}, '', self.window.pageview, self.window.ui) # XXX
			pageview = self.window.pageview
			pageview.insert_object(pageview.view.get_buffer(), obj)

	@action(_('Referen_ce...')) # T: menu item
	def insert_bibtex_ref(self):
		dialog = InsertBibTexRefDialog(self.window, self.window.pageview)
		lang = dialog.run()
		if not lang:
			return # dialog cancelled
		else:
			obj = BibTexRefObject({'type': OBJECT_TYPE_REF, 'bibname': dialog.bib.name, 'bibkey': dialog.bibKey}, '', dialog.bib, self.window.pageview, self.window.ui) # XXX
			pageview = self.window.pageview
			pageview.insert_object(pageview.view.get_buffer(), obj)

class InsertBibTexBibDialog(Dialog):

	object_type = 'bibtexBib'

	def __init__(self, ui, pageview):
		Dialog.__init__(self, ui, _('Insert BibTex'), # T: Dialog title
			button=(_('_Insert'), 'gtk-ok') # T: Button label
			)
		self.pageview = pageview
		
		self.template = get_template('plugins', 'equationeditor.tex')
		
		self.init_dialog()
			
	def init_dialog(self, table=None):
		table = gtk.Table(rows=2,columns=2)
		table.attach(gtk.Label("Name"), 0, 1, 0, 1)
		self.bibtexNameEntry = gtk.Entry()
		table.attach(self.bibtexNameEntry, 1, 2, 0, 1)
		table.attach(gtk.Label("Path"), 0, 1, 1, 2)
		self.bibtexPathEntry = gtk.Entry()
		table.attach(self.bibtexPathEntry, 1, 2, 1, 2)
		self.vbox.pack_start(table)

	def do_response_ok(self):
		self.bibName = self.bibtexNameEntry.get_text()
		self.bibPath = self.bibtexPathEntry.get_text()
		self.result = 1
		return True
		
	def cleanup(self):
		path = self.texfile.path
		for path in glob.glob(path[:-4]+'.*'):
			File(path).remove()
		
	def run(self):
		return Dialog.run(self)
		
class InsertBibTexRefDialog(Dialog):

	object_type = 'bibtexref'

	def __init__(self, ui, pageview):
		Dialog.__init__(self, ui, _('Insert Reference'), # T: Dialog title
			button=(_('_Insert'), 'gtk-ok') # T: Button label
			)
		self.pageview = pageview
		
		self.template = get_template('plugins', 'equationeditor.tex')
		
		self.init_dialog()
			
	def init_dialog(self, table=None):
		table = gtk.Table(rows=2,columns=2)
		table.attach(gtk.Label("Bibliography"), 0, 1, 0, 1)
		
		# get all available bibliographies in this pageview
		self.bibStore = gtk.ListStore(str, BibTexBibObject)
		for bib in BibTexBibObject.bibliographies[self.pageview]:
			self.bibStore.append([bib.name, bib])
			
		self.bibliography = gtk.ComboBox(self.bibStore)
		cell = gtk.CellRendererText()
		self.bibliography.pack_start(cell, True)
		self.bibliography.add_attribute(cell, 'text', 0)
		self.bibliography.connect('changed',self.on_bib_changed)
		
		table.attach(self.bibliography, 1, 2, 0, 1)
		table.attach(gtk.Label("Entry"), 0, 1, 1, 2)
		
		self.entryStore = gtk.ListStore(str)
		self.bibliographyEntry = gtk.ComboBox(self.entryStore)
		cell = gtk.CellRendererText()
		self.bibliographyEntry.pack_start(cell, True)
		self.bibliographyEntry.add_attribute(cell, 'text', 0)
		table.attach(self.bibliographyEntry, 1, 2, 1, 2)
		self.vbox.pack_start(table)
		
	def on_bib_changed(self, combobox):
		# get all keys from that bib and add it to the self.bibliographyEntry combobox
		self.entryStore.clear()
		
		for bla in combobox.get_model()[combobox.get_active()][1].bib_database.get_entry_list():
			self.entryStore.append([bla['ID']])
		

	def do_response_ok(self):
		#self.bibName = self.bibliography.get_model()[self.bibliography.get_active()][0]
		self.bib = self.bibliography.get_model()[self.bibliography.get_active()][1]
		self.bibKey = self.bibliographyEntry.get_model()[self.bibliographyEntry.get_active()][0]
		self.result = 1
		return True
		
	def cleanup(self):
		path = self.texfile.path
		for path in glob.glob(path[:-4]+'.*'):
			File(path).remove()
		
	def run(self):
		return Dialog.run(self)
		



class BibTexBibObject(CustomObjectClass):
	
	bibliographies = {}

	def __init__(self, attrib, text, pageview, ui=None):
		if not text is None and text.endswith('\n'):
			text = text[:-1]
			# If we have trailing \n it looks like an extra empty line
			# in the buffer, so we default remove one
		CustomObjectClass.__init__(self, attrib, text, ui)
		self.pageview = pageview
		self.referenceIds = {}
		self.references = {}
		ui.connect('close-page',self.on_close_page)
	
		#self.referenceStore = gtk.ListStore(str, str, str, str)
		self.referenceStore = gtk.ListStore(str, str, str)
		self.name = attrib['name']
		self.path = attrib['path']
		
		if not BibTexBibObject.bibliographies.has_key(pageview):
			BibTexBibObject.bibliographies[pageview] = []
		BibTexBibObject.bibliographies[pageview].append(self)
		
		# parse bibtex file	
		with open(self.path) as bibtex_file:
			bibtex_str = bibtex_file.read()
			
		self.bib_database = bibtexparser.loads(bibtex_str)
		
	def on_close_page(self, param1, param2, param3):
		BibTexBibObject.bibliographies.clear()
		BibTexEditorPlugin.unregisteredReferences.clear()

	def get_widget(self):
		if not self._widget:
			self._init_widget()
		return self._widget
		
	def get_data(self):
		'''Returns data as text.'''
		if self._widget:
			text = ""
			for row in self.referenceStore:
				text += (row[0] + ";" + row[1] + ";" + row[2] + "\n")
			return text
		return self._data

	def _init_widget(self):
		box = gtk.VBox()
		
		self.treeview = gtk.TreeView(self.referenceStore)
		self.treeview.set_headers_visible(False)
		
		column = gtk.TreeViewColumn()
		cellrender = gtk.CellRendererText()
		cellrender.props.wrap_width = 100
		cellrender.props.wrap_mode = gtk.WRAP_WORD
		column.pack_start(cellrender, True)
		column.add_attribute(cellrender, 'text', 0)
		self.treeview.append_column(column)
		column = gtk.TreeViewColumn()
		cellrender = gtk.CellRendererText()
		print(self.pageview.get_allocation()[3])
		cellrender.props.wrap_width = self.pageview.get_allocation()[2]
		cellrender.props.wrap_mode = gtk.WRAP_WORD
		column.pack_start(cellrender, True)
		column.add_attribute(cellrender, 'text', 2)
		self.treeview.append_column(column)
		#column = gtk.TreeViewColumn()
		#cellrender = gtk.CellRendererText()
		#column.pack_start(cellrender, True)
		#column.add_attribute(cellrender, 'text', 3)
		#self.treeview.append_column(column)
		
		box.pack_start(self.treeview)
		box.show_all()
		
		self._widget = CustomObjectBin()
		self._widget.add(box)
		
	def register_reference(self, reference):
		if not self.referenceIds.has_key(reference.bibKey):
			self.referenceIds[reference.bibKey] = len(self.referenceStore)+1
			self.references[reference.bibKey] = []
			#self.referenceStore.append([self.get_reference_id(reference.bibKey), reference.bibKey, self.bib_database.entries_dict[reference.bibKey]['author'], self.bib_database.entries_dict[reference.bibKey]['title']])
			refString = "%s, %s. %s" % (self.bib_database.entries_dict[reference.bibKey]['author'], self.bib_database.entries_dict[reference.bibKey]['title'], self.bib_database.entries_dict[reference.bibKey]['year'])
			self.referenceStore.append([self.get_reference_id(reference.bibKey), reference.bibKey, refString])
			reference.bibliography = self
			reference.label.set_text("[%d]" % self.referenceIds[reference.bibKey])
		self.references[reference.bibKey].append(reference)
		self.set_modified(True)
		
	def unregister_reference(self, reference):
		if self.references.has_key(reference.bibKey):
			if reference in self.references[reference.bibKey]:
				self.references[reference.bibKey].remove(reference)

				if len(self.references[reference.bibKey]) == 0:
					id = self.referenceIds[reference.bibKey]
					self.referenceStore.remove(self.referenceStore.get_iter(id-1))
					del self.references[reference.bibKey]
					del self.referenceIds[reference.bibKey]
					
					# update indices
					for bibKey in self.referenceIds.keys():
						if self.referenceIds[bibKey] > id:
							self.referenceIds[bibKey] = self.referenceIds[bibKey]-1
							self.referenceStore[self.referenceStore.get_iter(self.referenceIds[bibKey]-1)][0] = self.referenceIds[bibKey]
							for ref in self.references[bibKey]:
								ref.label.set_text("[%d]" % self.referenceIds[bibKey])
								ref.set_modified(True)
					self.set_modified(True)
		
	def get_reference_id(self, reference):
		return self.referenceIds[reference]

class BibTexRefObject(CustomObjectClass):

	def __init__(self, attrib, data, bibliography, pageview, ui=None):
		#if data.endswith('\n'):
		#	data = data[:-1]
			# If we have trailing \n it looks like an extra empty line
			# in the buffer, so we default remove one
		CustomObjectClass.__init__(self, attrib, data, ui)
		self.data = None
		self.pageview = pageview
		self.pageview.view.get_buffer().connect_after('delete-range',self.on_delete_range)
		self.anchor = None
		self.label = gtk.Label("")
		
		self.bibKey = attrib['bibkey']
		self.bibliography = bibliography
		if not bibliography is None:
			self.bibliography.register_reference(self)
		
	def on_delete_range(self, textbuffer, start, end):
		if self.anchor.get_deleted():
			if not self.bibliography is None:
				self.bibliography.unregister_reference(self)

	def get_widget(self):
		if not self._widget:
			self._init_widget()
		return self._widget
		
	def get_data(self):
		'''Returns data as text.'''
		if self._widget:
			text = ""
			return text
		return self._data

	def _init_widget(self):
		if not self.bibliography is None:
			self.label.set_text("[%d]" % self.bibliography.get_reference_id(self.bibKey))
		else:
			self.label.set_text("[...]")
		self.label.set_padding(0,0)
		
		self._widget = CustomObjectBin()
		self._widget.set_border_width(0)
		
		self._widget.add(self.label)
		
	# TODO: teardown; remove reference from bibliography
