from .logging import addLogEntry
from PyQt5 import QtGui, QtWidgets, uic
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtCore import pyqtSignal, Qt
from qgis.gui import QgsMapToolEmitPoint
from qgis.core import QgsVectorLayer, QgsProject
from datetime import datetime
from .config import Config
from .api import API
import urllib.parse
import json
import io
import os
from os.path import expanduser

home = expanduser("~")

methodModes = {
    'category_search': ['categoryGroup', 'searchGroup'],
    'bounding_box': ['bboxGroup', 'categoryGroup', 'searchGroup'],
    'reference_search': ['refGroup', 'categoryGroup'],
    'point_search': ['locationGroup', 'distGroup'],
}

class SearchWidget():
    SearchDock, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), '../UI/Search.ui'))

    class widget(QtWidgets.QDockWidget, SearchDock):
        closingPlugin = pyqtSignal()

        def __init__(self, iface, parent=None):
            super(SearchWidget.widget, self).__init__(parent)
            self.setupUi(self)
            self.canvas = iface.mapCanvas()
            self.iface = iface

            self.widgetGroups = {
                'categoryGroup': self.categoryGroup,
                'refGroup': self.refGroup,
                'distGroup': self.distGroup,
                'searchGroup': self.searchGroup,
                'locationGroup': self.locationGroup,
                'bboxGroup': self.bboxGroup,
            }

            self.bboxStarted = False
            self.queryLayers = {
                'category_search': False,
                'bounding_box': False,
                'reference_search': False,
                'point_search': False,
            }

            for key in self.queryLayers:
                layers = QgsProject.instance().mapLayersByName('Locus_API_' + key + '_query_results')
                if len(layers) > 0:
                    self.queryLayers[key] = layers[0]

            self.options = {
                'category': '',
                'method': 'list_categories',
                'search_text': '',
                'location': {
                    'x': 0,
                    'y': 0,
                },
                'bbox': [0, 0, 0, 0],
                'crs': 'SRID=4326',
                'reference': '',
                'distance': '',
            }

            self.locationTool = QgsMapToolEmitPoint(self.canvas)
            self.locationTool.canvasClicked.connect(self.setLocation)
            self.locationButton.clicked.connect(self.startLocationSet)
            self.bboxTool = QgsMapToolEmitPoint(self.canvas)
            self.bboxTool.canvasClicked.connect(self.setBBox)
            self.bboxButton.clicked.connect(self.startBBoxSet)

            options = API.makeCall(self.options)
            if not options:
                self.toggleInputs(False, False)
            else:
                self.categoryCombo.addItem('')
                self.options['category'] = ''
                self.options['method'] = 'category_search'
                self.toggleVisible('category_search')

                for option in options:
                    if isinstance(option, str):
                        self.categoryCombo.addItem(option)

            self.categoryCombo.activated[str].connect(self.categoryChanged)
            self.modeCombo.activated[str].connect(self.methodChanged)

            # Open the settings widget on button click
            widget = SettingsWidget.widget(iface)
            self.settingsButton.clicked.connect(lambda: WidgetManager.ChangeWidget(widget, False))

            self.runButton.clicked.connect(self.runQuery)
            self.adjustSize()

        def toggleVisible(self, mode):
            for group in self.widgetGroups:
                self.widgetGroups[group].setVisible(False)

            for option in methodModes[mode]:
                self.widgetGroups[option].setVisible(True)

            self.adjustSize()

        def toggleInputs(self, enabled, settings=True):
            if settings:
                self.settingsButton.setEnabled(enabled)
            self.locationGroup.setEnabled(enabled)
            self.bboxGroup.setEnabled(enabled)
            self.runButton.setEnabled(enabled)
            self.searchGroup.setEnabled(enabled)
            self.categoryGroup.setEnabled(enabled)
            self.refGroup.setEnabled(enabled)
            self.distGroup.setEnabled(enabled)
            self.modeCombo.setEnabled(enabled)

        def startBBoxSet(self):
            self.toggleInputs(False)
            self.canvas.setMapTool(self.bboxTool)

        def setBBox(self):
            point = self.canvas.getCoordinateTransform().toMapCoordinates(self.canvas.mouseLastXY())
            if not self.bboxStarted:
                self.bboxStarted = True
                self.options['bbox'] = [ point[0], point[1] ]
                self.bboxMinXLabel.setText('Min X: ' + str(point[0]))
                self.bboxMinYLabel.setText('Min Y: ' + str(point[1]))
            else:
                self.bboxStarted = False
                self.options['bbox'].append(point[0])
                self.options['bbox'].append(point[1])

                if self.options['bbox'][0] > self.options['bbox'][2]:
                    tmp = self.options['bbox'][0]
                    self.options['bbox'][0] = self.options['bbox'][2]
                    self.options['bbox'][2] = tmp

                if self.options['bbox'][1] > self.options['bbox'][3]:
                    tmp = self.options['bbox'][1]
                    self.options['bbox'][1] = self.options['bbox'][3]
                    self.options['bbox'][3] = tmp

                self.bboxMinXLabel.setText('Min X: ' + str(self.options['bbox'][0]))
                self.bboxMinYLabel.setText('Min Y: ' + str(self.options['bbox'][1]))
                self.bboxMaxXLabel.setText('Max X: ' + str(self.options['bbox'][2]))
                self.bboxMaxYLabel.setText('Max Y: ' + str(self.options['bbox'][3]))

                self.canvas.unsetMapTool(self.bboxTool)
                self.toggleInputs(True)

        def startLocationSet(self):
            self.toggleInputs(False)
            self.canvas.setMapTool(self.locationTool)

        def setLocation(self):
            point = self.canvas.getCoordinateTransform().toMapCoordinates(self.canvas.mouseLastXY())
            self.options['location'] = {
                'x': point[0],
                'y': point[1],
            }

            self.locationXLabel.setText('X: ' + str(point[0]))
            self.locationYLabel.setText('Y: ' + str(point[1]))
            self.canvas.unsetMapTool(self.locationTool)
            self.toggleInputs(True)

        def runQuery(self):
            self.options['crs'] = 'SRID=' + self.canvas.mapSettings().destinationCrs().authid().split(':')[1]
            self.options['search_text'] = urllib.parse.quote(self.searchField.text(), safe='')
            self.options['distance'] = urllib.parse.quote(self.distanceField.text(), safe='')
            self.options['reference'] = urllib.parse.quote(self.referenceField.text(), safe='')
            self.toggleInputs(False)

            call = API.makeCall(self.options, debug=True)
            if not call:
                self.toggleInputs(True)
                return

            if len(call['features']) < 1:
                QMessageBox.information(None, 'Data Warning', 'No features were returned from the query')
                self.toggleInputs(True)
                return

            data = json.dumps(call)
            date = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            fileName = home + '/Xmpli/tmp/Locus_' + date + '_' + self.options['method'] + '_results.json'
            addLogEntry('Create cache file: ' + fileName)

            with io.open(fileName, 'w+', encoding="utf-8") as wf:
                wf.write(data)

            addLogEntry('Create Layer')
            queryLayer = QgsVectorLayer(fileName, 'Locus_API_' + self.options['method'] + '_query_results', 'ogr')
            addLogEntry('Add Layer')
            QgsProject.instance().addMapLayer(queryLayer)
            self.toggleInputs(True)


        def categoryChanged(self, category):
            self.options['category'] = category

        def methodChanged(self, option):
            self.toggleVisible(option)
            self.options['method'] = option

        def closeEvent(self, event):
            self.closingPlugin.emit()
            event.accept()

class SettingsWidget():
    SettingsDock, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), '../UI/Settings.ui'))

    class widget(QtWidgets.QDockWidget, SettingsDock):
        closingPlugin = pyqtSignal()

        def __init__(self, iface, parent=None):
            super(SettingsWidget.widget, self).__init__(parent)
            self.settings = Config.getConfig()
            self.setupUi(self)
            self.iface = iface
            self.endpointField.setText(self.settings['endpoint'])
            self.saveButton.clicked.connect(self.updateConfig)
            self.cancelButton.clicked.connect(self.returnToSearch)

        def updateConfig(self):
            endpoint = self.endpointField.text()
            self.settings['endpoint'] = endpoint
            Config.updateConfig(self.settings)
            self.returnToSearch()

        def returnToSearch(self):
            # Go back to the main search widget
            widget = SearchWidget.widget(self.iface)
            WidgetManager.ChangeWidget(widget, False)

        def closeEvent(self, event):
            self.closingPlugin.emit()
            event.accept()

class WidgetManager():
    main = None

    def __init__(self, plugin):
        WidgetManager.main = plugin

    @staticmethod
    def ChangeWidget(new_widget, docked=True, init_script=None):
        WidgetManager.main.dockwidget = new_widget
        WidgetManager.main.dockwidget.closingPlugin.connect(WidgetManager.main.onClosePlugin)
        if docked:
            WidgetManager.main.iface.addDockWidget(Qt.LeftDockWidgetArea, WidgetManager.main.dockwidget)
        if init_script is not None:
            init_script()
        WidgetManager.main.dockwidget.show()
