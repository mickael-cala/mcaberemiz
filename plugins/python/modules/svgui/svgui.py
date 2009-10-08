import wx
import os, sys, shutil

from plugger import opjimg
from plugins.python import PythonCodeTemplate

from pyjs import translate

from docutils import *

class RootClass:

    PluginMethods = [
        {"bitmap" : os.path.join("images","ImportSVG"),
         "name" : "Import SVG",
         "tooltip" : "Import SVG",
         "method" : "_ImportSVG"},
        {"bitmap" : os.path.join("images","ImportSVG"),
         "name" : "Inkscape",
         "tooltip" : "Create HMI",
         "method" : "_StartInkscape"},
    ]

    def PluginPath(self):
        return os.path.join(self.PlugParent.PluginPath(), "modules", self.PlugType)

    def _getSVGpath(self):
        # define name for IEC raw code file
        return os.path.join(self.PlugPath(), "gui.svg")

    def _getSVGUIserverpath(self):
        return os.path.join(os.path.dirname(__file__), "svgui_server.py")

    def PlugGenerate_C(self, buildpath, locations):
        """
        Return C code generated by iec2c compiler 
        when _generate_softPLC have been called
        @param locations: ignored
        @return: [(C_file_name, CFLAGS),...] , LDFLAGS_TO_APPEND
        """
        
        current_location = self.GetCurrentLocation()
        # define a unique name for the generated C file
        location_str = "_".join(map(lambda x:str(x), current_location))
        
        res = ([], "", False)
        
        svgfile=self._getSVGpath()
        if os.path.exists(svgfile):
            res += (("gui.svg", file(svgfile,"rb")),)

        svguiserverfile = open(self._getSVGUIserverpath(), 'r')
        svguiservercode = svguiserverfile.read()
        svguiserverfile.close()

        svguilibpath = os.path.join(self._getBuildPath(), "svguilib.js")
        svguilibfile = open(svguilibpath, 'w')
        svguilibfile.write(translate(os.path.join(os.path.dirname(__file__), "pyjs", "lib", "sys.py"), "sys"))
        svguilibfile.write(open(os.path.join(os.path.dirname(__file__), "pyjs", "lib", "_pyjs.js"), 'r').read())
        svguilibfile.write(translate(os.path.join(os.path.dirname(__file__), "pyjs", "lib", "pyjslib.py"), "pyjslib"))
        svguilibfile.write(translate(os.path.join(os.path.dirname(__file__), "svguilib.py"), "svguilib"))
        svguilibfile.write("pyjslib();\nsvguilib();\n")
        svguilibfile.write(open(os.path.join(os.path.dirname(__file__), "pyjs", "lib", "json.js"), 'r').read())
        svguilibfile.write(open(os.path.join(os.path.dirname(__file__), "livesvg.js"), 'r').read())
        svguilibfile.close()
        jsmodules = {"LiveSVGPage": "svguilib.js"}
        res += (("svguilib.js", file(svguilibpath,"rb")),)
        
        runtimefile_path = os.path.join(buildpath, "runtime_%s.py"%location_str)
        runtimefile = open(runtimefile_path, 'w')
        runtimefile.write(svguiservercode % {"svgfile" : "gui.svg"})
        runtimefile.write("""
def _runtime_%(location)s_begin():
    website.LoadHMI(%(svgui_class)s, %(jsmodules)s)
    
def _runtime_%(location)s_cleanup():
    website.UnLoadHMI()
    
""" % {"location": location_str,
       "svgui_class": "SVGUI_HMI",
       "jsmodules" : str(jsmodules),
      })
        runtimefile.close()
        
        res += (("runtime_%s.py"%location_str, file(runtimefile_path,"rb")),)
        
        return res

    def _ImportSVG(self):
        dialog = wx.FileDialog(self.GetPlugRoot().AppFrame, "Choose a SVG file", os.getcwd(), "",  "SVG files (*.svg)|*.svg|All files|*.*", wx.OPEN)
        if dialog.ShowModal() == wx.ID_OK:
            svgpath = dialog.GetPath()
            if os.path.isfile(svgpath):
                shutil.copy(svgpath, self._getSVGpath())
            else:
                self.logger.write_error("No such SVG file: %s\n"%svgpath)
        dialog.Destroy()  

    def _StartInkscape(self):
        svgfile = self._getSVGpath()
        if not os.path.isfile(svgfile):
            svgfile = None
        open_svg(svgfile)
