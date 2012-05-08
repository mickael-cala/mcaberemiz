"""
Base definitions for beremiz confnodes
"""

import os,sys,traceback
import time
import confnodes
import types
import shutil
from xml.dom import minidom
import wx

#Quick hack to be able to find Beremiz IEC tools. Should be config params.
base_folder = os.path.split(sys.path[0])[0]

from xmlclass import GenerateClassesFromXSDstring
from wxPopen import ProcessLogger

from PLCControler import PLCControler, LOCATION_CONFNODE, LOCATION_MODULE, LOCATION_GROUP, LOCATION_VAR_INPUT, LOCATION_VAR_OUTPUT, LOCATION_VAR_MEMORY

_BaseParamsClass = GenerateClassesFromXSDstring("""<?xml version="1.0" encoding="ISO-8859-1" ?>
        <xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">
          <xsd:element name="BaseParams">
            <xsd:complexType>
              <xsd:attribute name="Name" type="xsd:string" use="optional" default="__unnamed__"/>
              <xsd:attribute name="IEC_Channel" type="xsd:integer" use="required"/>
              <xsd:attribute name="Enabled" type="xsd:boolean" use="optional" default="true"/>
            </xsd:complexType>
          </xsd:element>
        </xsd:schema>""")["BaseParams"]

NameTypeSeparator = '@'

class MiniTextControler:
    
    def __init__(self, filepath):
        self.FilePath = filepath
    
    def CTNFullName(self):
        return ""
    
    def SetEditedElementText(self, tagname, text):
        file = open(self.FilePath, "w")
        file.write(text)
        file.close()
        
    def GetEditedElementText(self, tagname, debug = False):
        if os.path.isfile(self.FilePath):
            file = open(self.FilePath, "r")
            text = file.read()
            file.close()
            return text
        return ""
    
    def GetEditedElementInterfaceVars(self, tagname, debug = False):
        return []
    
    def GetEditedElementType(self, tagname, debug = False):
        return "program"
    
    def GetBlockTypes(self, tagname = "", debug = False):
        return []
    
    def GetDataTypes(self, tagname = "", basetypes = True, only_locatables = False, debug = False):
        return []
    
    def GetEnumeratedDataValues(self, debug = False):
        return []
    
    def StartBuffering(self):
        pass

    def EndBuffering(self):
        pass

    def BufferProject(self):
        pass

# helper func to get path to images
def opjimg(imgname):
    return os.path.join(base_folder, "beremiz", "images",imgname)
    
# helper func to check path write permission
def CheckPathPerm(path):
    if path is None or not os.path.isdir(path):
        return False
    for root, dirs, files in os.walk(path):
         for name in files:
             if os.access(root, os.W_OK) is not True or os.access(os.path.join(root, name), os.W_OK) is not True:
                 return False
    return True
    
class ConfigTreeNode:
    """
    This class is the one that define confnodes.
    """

    XSD = None
    CTNChildrenTypes = []
    CTNMaxCount = None
    ConfNodeMethods = []
    LibraryControler = None
    EditorType = None

    def _AddParamsMembers(self):
        self.CTNParams = None
        if self.XSD:
            self.Classes = GenerateClassesFromXSDstring(self.XSD)
            Classes = [(name, XSDclass) for name, XSDclass in self.Classes.items() if XSDclass.IsBaseClass]
            if len(Classes) == 1:
                name, XSDclass = Classes[0]
                obj = XSDclass()
                self.CTNParams = (name, obj)
                setattr(self, name, obj)

    def __init__(self):
        # Create BaseParam 
        self.BaseParams = _BaseParamsClass()
        self.MandatoryParams = ("BaseParams", self.BaseParams)
        self._AddParamsMembers()
        self.Children = {}
        self._View = None
        # copy ConfNodeMethods so that it can be later customized
        self.ConfNodeMethods = [dic.copy() for dic in self.ConfNodeMethods]
        self.LoadSTLibrary()
        
    def ConfNodeBaseXmlFilePath(self, CTNName=None):
        return os.path.join(self.CTNPath(CTNName), "baseconfnode.xml")
    
    def ConfNodeXmlFilePath(self, CTNName=None):
        return os.path.join(self.CTNPath(CTNName), "confnode.xml")

    def ConfNodeLibraryFilePath(self):
        return os.path.join(self.ConfNodePath(), "pous.xml")

    def ConfNodePath(self):
        return os.path.join(self.CTNParent.ConfNodePath(), self.CTNType)

    def CTNPath(self,CTNName=None):
        if not CTNName:
            CTNName = self.CTNName()
        return os.path.join(self.CTNParent.CTNPath(),
                            CTNName + NameTypeSeparator + self.CTNType)
    
    def CTNName(self):
        return self.BaseParams.getName()
    
    def CTNEnabled(self):
        return self.BaseParams.getEnabled()
    
    def CTNFullName(self):
        parent = self.CTNParent.CTNFullName()
        if parent != "":
            return parent + "." + self.CTNName()
        return self.BaseParams.getName()
    
    def GetIconPath(self, name):
        return opjimg(name)
    
    def CTNTestModified(self):
        return self.ChangesToSave

    def ProjectTestModified(self):
        """
        recursively check modified status
        """
        if self.CTNTestModified():
            return True

        for CTNChild in self.IterChildren():
            if CTNChild.ProjectTestModified():
                return True

        return False
    
    def RemoteExec(self, script, **kwargs):
        return self.CTNParent.RemoteExec(script, **kwargs)
    
    def OnCTNSave(self):
        #Default, do nothing and return success
        return True

    def GetParamsAttributes(self, path = None):
        if path:
            parts = path.split(".", 1)
            if self.MandatoryParams and parts[0] == self.MandatoryParams[0]:
                return self.MandatoryParams[1].getElementInfos(parts[0], parts[1])
            elif self.CTNParams and parts[0] == self.CTNParams[0]:
                return self.CTNParams[1].getElementInfos(parts[0], parts[1])
        else:
            params = []
            if wx.VERSION < (2, 8, 0) and self.MandatoryParams:
                params.append(self.MandatoryParams[1].getElementInfos(self.MandatoryParams[0]))
            if self.CTNParams:
                params.append(self.CTNParams[1].getElementInfos(self.CTNParams[0]))
            return params
        
    def SetParamsAttribute(self, path, value):
        self.ChangesToSave = True
        # Filter IEC_Channel and Name, that have specific behavior
        if path == "BaseParams.IEC_Channel":
            old_leading = ".".join(map(str, self.GetCurrentLocation()))
            new_value = self.FindNewIEC_Channel(value)
            new_leading = ".".join(map(str, self.CTNParent.GetCurrentLocation() + (new_value,)))
            self.GetCTRoot().UpdateProjectVariableLocation(old_leading, new_leading)
            return new_value, True
        elif path == "BaseParams.Name":
            res = self.FindNewName(value)
            self.CTNRequestSave()
            return res, True
        
        parts = path.split(".", 1)
        if self.MandatoryParams and parts[0] == self.MandatoryParams[0]:
            self.MandatoryParams[1].setElementValue(parts[1], value)
        elif self.CTNParams and parts[0] == self.CTNParams[0]:
            self.CTNParams[1].setElementValue(parts[1], value)
        return value, False

    def CTNMakeDir(self):
        os.mkdir(self.CTNPath())

    def CTNRequestSave(self):
        if self.GetCTRoot().CheckProjectPathPerm(False):
            # If confnode do not have corresponding directory
            ctnpath = self.CTNPath()
            if not os.path.isdir(ctnpath):
                # Create it
                os.mkdir(ctnpath)
    
            # generate XML for base XML parameters controller of the confnode
            if self.MandatoryParams:
                BaseXMLFile = open(self.ConfNodeBaseXmlFilePath(),'w')
                BaseXMLFile.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
                BaseXMLFile.write(self.MandatoryParams[1].generateXMLText(self.MandatoryParams[0], 0).encode("utf-8"))
                BaseXMLFile.close()
            
            # generate XML for XML parameters controller of the confnode
            if self.CTNParams:
                XMLFile = open(self.ConfNodeXmlFilePath(),'w')
                XMLFile.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
                XMLFile.write(self.CTNParams[1].generateXMLText(self.CTNParams[0], 0).encode("utf-8"))
                XMLFile.close()
            
            # Call the confnode specific OnCTNSave method
            result = self.OnCTNSave()
            if not result:
                return _("Error while saving \"%s\"\n")%self.CTNPath()
    
            # mark confnode as saved
            self.ChangesToSave = False
            # go through all children and do the same
            for CTNChild in self.IterChildren():
                result = CTNChild.CTNRequestSave()
                if result:
                    return result
        return None
    
    def CTNImport(self, src_CTNPath):
        shutil.copytree(src_CTNPath, self.CTNPath)
        return True

    def CTNGenerate_C(self, buildpath, locations):
        """
        Generate C code
        @param locations: List of complete variables locations \
            [{"IEC_TYPE" : the IEC type (i.e. "INT", "STRING", ...)
            "NAME" : name of the variable (generally "__IW0_1_2" style)
            "DIR" : direction "Q","I" or "M"
            "SIZE" : size "X", "B", "W", "D", "L"
            "LOC" : tuple of interger for IEC location (0,1,2,...)
            }, ...]
        @return: [(C_file_name, CFLAGS),...] , LDFLAGS_TO_APPEND
        """
        self.GetCTRoot().logger.write_warning(".".join(map(lambda x:str(x), self.GetCurrentLocation())) + " -> Nothing to do\n")
        return [],"",False
    
    def _Generate_C(self, buildpath, locations):
        # Generate confnodes [(Cfiles, CFLAGS)], LDFLAGS, DoCalls, extra_files
        # extra_files = [(fname,fobject), ...]
        gen_result = self.CTNGenerate_C(buildpath, locations)
        CTNCFilesAndCFLAGS, CTNLDFLAGS, DoCalls = gen_result[:3]
        extra_files = gen_result[3:]
        # if some files have been generated put them in the list with their location
        if CTNCFilesAndCFLAGS:
            LocationCFilesAndCFLAGS = [(self.GetCurrentLocation(), CTNCFilesAndCFLAGS, DoCalls)]
        else:
            LocationCFilesAndCFLAGS = []

        # confnode asks for some LDFLAGS
        if CTNLDFLAGS:
            # LDFLAGS can be either string
            if type(CTNLDFLAGS)==type(str()):
                LDFLAGS=[CTNLDFLAGS]
            #or list of strings
            elif type(CTNLDFLAGS)==type(list()):
                LDFLAGS=CTNLDFLAGS[:]
        else:
            LDFLAGS=[]
        
        # recurse through all children, and stack their results
        for CTNChild in self.IECSortedChildren():
            new_location = CTNChild.GetCurrentLocation()
            # How deep are we in the tree ?
            depth=len(new_location)
            _LocationCFilesAndCFLAGS, _LDFLAGS, _extra_files = \
                CTNChild._Generate_C(
                    #keep the same path
                    buildpath,
                    # filter locations that start with current IEC location
                    [loc for loc in locations if loc["LOC"][0:depth] == new_location ])
            # stack the result
            LocationCFilesAndCFLAGS += _LocationCFilesAndCFLAGS
            LDFLAGS += _LDFLAGS
            extra_files += _extra_files
        
        return LocationCFilesAndCFLAGS, LDFLAGS, extra_files

    def ConfNodeTypesFactory(self):
        if self.LibraryControler is not None:
            return [{"name" : self.CTNType, "types": self.LibraryControler.Project}]
        return []

    def ParentsTypesFactory(self):
        return self.CTNParent.ParentsTypesFactory() + self.ConfNodeTypesFactory()

    def ConfNodesTypesFactory(self):
        list = self.ConfNodeTypesFactory()
        for CTNChild in self.IterChildren():
            list += CTNChild.ConfNodesTypesFactory()
        return list

    def STLibraryFactory(self):
        if self.LibraryControler is not None:
            program, errors, warnings = self.LibraryControler.GenerateProgram()
            return program + "\n"
        return ""

    def ConfNodesSTLibraryFactory(self):
        program = self.STLibraryFactory()
        for CTNChild in self.IECSortedChildren():
            program += CTNChild.ConfNodesSTLibraryFactory()
        return program
        
    def IterChildren(self):
        for CTNType, Children in self.Children.items():
            for CTNInstance in Children:
                yield CTNInstance
    
    def IECSortedChildren(self):
        # reorder children by IEC_channels
        ordered = [(chld.BaseParams.getIEC_Channel(),chld) for chld in self.IterChildren()]
        if ordered:
            ordered.sort()
            return zip(*ordered)[1]
        else:
            return []
    
    def _GetChildBySomething(self, something, toks):
        for CTNInstance in self.IterChildren():
            # if match component of the name
            if getattr(CTNInstance.BaseParams, something) == toks[0]:
                # if Name have other components
                if len(toks) >= 2:
                    # Recurse in order to find the latest object
                    return CTNInstance._GetChildBySomething( something, toks[1:])
                # No sub name -> found
                return CTNInstance
        # Not found
        return None

    def GetChildByName(self, Name):
        if Name:
            toks = Name.split('.')
            return self._GetChildBySomething("Name", toks)
        else:
            return self

    def GetChildByIECLocation(self, Location):
        if Location:
            return self._GetChildBySomething("IEC_Channel", Location)
        else:
            return self
    
    def GetCurrentLocation(self):
        """
        @return:  Tupple containing confnode IEC location of current confnode : %I0.0.4.5 => (0,0,4,5)
        """
        return self.CTNParent.GetCurrentLocation() + (self.BaseParams.getIEC_Channel(),)

    def GetCurrentName(self):
        """
        @return:  String "ParentParentName.ParentName.Name"
        """
        return  self.CTNParent._GetCurrentName() + self.BaseParams.getName()

    def _GetCurrentName(self):
        """
        @return:  String "ParentParentName.ParentName.Name."
        """
        return  self.CTNParent._GetCurrentName() + self.BaseParams.getName() + "."

    def GetCTRoot(self):
        return self.CTNParent.GetCTRoot()

    def GetFullIEC_Channel(self):
        return ".".join([str(i) for i in self.GetCurrentLocation()]) + ".x"

    def GetLocations(self):
        location = self.GetCurrentLocation()
        return [loc for loc in self.CTNParent.GetLocations() if loc["LOC"][0:len(location)] == location]

    def GetVariableLocationTree(self):
        '''
        This function is meant to be overridden by confnodes.

        It should returns an list of dictionaries
        
        - IEC_type is an IEC type like BOOL/BYTE/SINT/...
        - location is a string of this variable's location, like "%IX0.0.0"
        '''
        children = []
        for child in self.IECSortedChildren():
            children.append(child.GetVariableLocationTree())
        return {"name": self.BaseParams.getName(),
                "type": LOCATION_CONFNODE,
                "location": self.GetFullIEC_Channel(),
                "children": children}

    def FindNewName(self, DesiredName):
        """
        Changes Name to DesiredName if available, Name-N if not.
        @param DesiredName: The desired Name (string)
        """
        # Get Current Name
        CurrentName = self.BaseParams.getName()
        # Do nothing if no change
        #if CurrentName == DesiredName: return CurrentName
        # Build a list of used Name out of parent's Children
        AllNames=[]
        for CTNInstance in self.CTNParent.IterChildren():
            if CTNInstance != self:
                AllNames.append(CTNInstance.BaseParams.getName())

        # Find a free name, eventually appending digit
        res = DesiredName
        suffix = 1
        while res in AllNames:
            res = "%s-%d"%(DesiredName, suffix)
            suffix += 1
        
        # Get old path
        oldname = self.CTNPath()
        # Check previous confnode existance
        dontexist = self.BaseParams.getName() == "__unnamed__"
        # Set the new name
        self.BaseParams.setName(res)
        # Rename confnode dir if exist
        if not dontexist:
            shutil.move(oldname, self.CTNPath())
        # warn user he has two left hands
        if DesiredName != res:
            self.GetCTRoot().logger.write_warning(_("A child names \"%s\" already exist -> \"%s\"\n")%(DesiredName,res))
        return res

    def GetAllChannels(self):
        AllChannels=[]
        for CTNInstance in self.CTNParent.IterChildren():
            if CTNInstance != self:
                AllChannels.append(CTNInstance.BaseParams.getIEC_Channel())
        AllChannels.sort()
        return AllChannels

    def FindNewIEC_Channel(self, DesiredChannel):
        """
        Changes IEC Channel number to DesiredChannel if available, nearest available if not.
        @param DesiredChannel: The desired IEC channel (int)
        """
        # Get Current IEC channel
        CurrentChannel = self.BaseParams.getIEC_Channel()
        # Do nothing if no change
        #if CurrentChannel == DesiredChannel: return CurrentChannel
        # Build a list of used Channels out of parent's Children
        AllChannels = self.GetAllChannels()
        
        # Now, try to guess the nearest available channel
        res = DesiredChannel
        while res in AllChannels: # While channel not free
            if res < CurrentChannel: # Want to go down ?
                res -=  1 # Test for n-1
                if res < 0 :
                    self.GetCTRoot().logger.write_warning(_("Cannot find lower free IEC channel than %d\n")%CurrentChannel)
                    return CurrentChannel # Can't go bellow 0, do nothing
            else : # Want to go up ?
                res +=  1 # Test for n-1
        # Finally set IEC Channel
        self.BaseParams.setIEC_Channel(res)
        return res

    def _OpenView(self, name=None):
        if self.EditorType is not None and self._View is None:
            app_frame = self.GetCTRoot().AppFrame
            
            self._View = self.EditorType(app_frame.TabsOpened, self, app_frame)
            
            app_frame.EditProjectElement(self._View, self.CTNName())
            
            return self._View
        return None

    def OnCloseEditor(self, view):
        if self._View == view:
            self._View = None

    def OnCTNClose(self):
        if self._View is not None:
            app_frame = self.GetCTRoot().AppFrame
            if app_frame is not None:
                app_frame.DeletePage(self._View)
        return True

    def _doRemoveChild(self, CTNInstance):
        # Remove all children of child
        for SubCTNInstance in CTNInstance.IterChildren():
            CTNInstance._doRemoveChild(SubCTNInstance)
        # Call the OnCloseMethod
        CTNInstance.OnCTNClose()
        # Delete confnode dir
        shutil.rmtree(CTNInstance.CTNPath())
        # Remove child of Children
        self.Children[CTNInstance.CTNType].remove(CTNInstance)
        # Forget it... (View have to refresh)

    def CTNRemove(self):
        # Fetch the confnode
        #CTNInstance = self.GetChildByName(CTNName)
        # Ask to his parent to remove it
        self.CTNParent._doRemoveChild(self)

    def CTNAddChild(self, CTNName, CTNType, IEC_Channel=0):
        """
        Create the confnodes that may be added as child to this node self
        @param CTNType: string desining the confnode class name (get name from CTNChildrenTypes)
        @param CTNName: string for the name of the confnode instance
        """
        # reorgabize self.CTNChildrenTypes tuples from (name, CTNClass, Help)
        # to ( name, (CTNClass, Help)), an make a dict
        transpose = zip(*self.CTNChildrenTypes)
        CTNChildrenTypes = dict(zip(transpose[0],zip(transpose[1],transpose[2])))
        # Check that adding this confnode is allowed
        try:
            CTNClass, CTNHelp = CTNChildrenTypes[CTNType]
        except KeyError:
            raise Exception, _("Cannot create child %s of type %s ")%(CTNName, CTNType)
        
        # if CTNClass is a class factory, call it. (prevent unneeded imports)
        if type(CTNClass) == types.FunctionType:
            CTNClass = CTNClass()
        
        # Eventualy Initialize child instance list for this class of confnode
        ChildrenWithSameClass = self.Children.setdefault(CTNType, list())
        # Check count
        if getattr(CTNClass, "CTNMaxCount", None) and len(ChildrenWithSameClass) >= CTNClass.CTNMaxCount:
            raise Exception, _("Max count (%d) reached for this confnode of type %s ")%(CTNClass.CTNMaxCount, CTNType)
        
        # create the final class, derived of provided confnode and template
        class FinalCTNClass(CTNClass, ConfigTreeNode):
            """
            ConfNode class is derivated into FinalCTNClass before being instanciated
            This way __init__ is overloaded to ensure ConfigTreeNode.__init__ is called 
            before CTNClass.__init__, and to do the file related stuff.
            """
            def __init__(_self):
                # self is the parent
                _self.CTNParent = self
                # Keep track of the confnode type name
                _self.CTNType = CTNType
                # remind the help string, for more fancy display
                _self.CTNHelp = CTNHelp
                # Call the base confnode template init - change XSD into class members
                ConfigTreeNode.__init__(_self)
                # check name is unique
                NewCTNName = _self.FindNewName(CTNName)
                # If dir have already be made, and file exist
                if os.path.isdir(_self.CTNPath(NewCTNName)): #and os.path.isfile(_self.ConfNodeXmlFilePath(CTNName)):
                    #Load the confnode.xml file into parameters members
                    _self.LoadXMLParams(NewCTNName)
                    # Basic check. Better to fail immediately.
                    if (_self.BaseParams.getName() != NewCTNName):
                        raise Exception, _("Project tree layout do not match confnode.xml %s!=%s ")%(NewCTNName, _self.BaseParams.getName())

                    # Now, self.CTNPath() should be OK
                    
                    # Check that IEC_Channel is not already in use.
                    _self.FindNewIEC_Channel(_self.BaseParams.getIEC_Channel())
                    # Call the confnode real __init__
                    if getattr(CTNClass, "__init__", None):
                        CTNClass.__init__(_self)
                    #Load and init all the children
                    _self.LoadChildren()
                    #just loaded, nothing to saved
                    _self.ChangesToSave = False
                else:
                    # If confnode do not have corresponding file/dirs - they will be created on Save
                    _self.CTNMakeDir()
                    # Find an IEC number
                    _self.FindNewIEC_Channel(IEC_Channel)
                    # Call the confnode real __init__
                    if getattr(CTNClass, "__init__", None):
                        CTNClass.__init__(_self)
                    _self.CTNRequestSave()
                    #just created, must be saved
                    _self.ChangesToSave = True
                
            def _getBuildPath(_self):
                return self._getBuildPath()
            
        # Create the object out of the resulting class
        newConfNodeOpj = FinalCTNClass()
        # Store it in CTNgedChils
        ChildrenWithSameClass.append(newConfNodeOpj)
        
        return newConfNodeOpj
    
    def ClearChildren(self):
        for child in self.IterChildren():
            child.ClearChildren()
        self.Children = {}
    
    def LoadSTLibrary(self):
        # Get library blocks if plcopen library exist
        library_path = self.ConfNodeLibraryFilePath()
        if os.path.isfile(library_path):
            self.LibraryControler = PLCControler()
            self.LibraryControler.OpenXMLFile(library_path)
            self.LibraryControler.ClearConfNodeTypes()
            self.LibraryControler.AddConfNodeTypesList(self.ParentsTypesFactory())

    def LoadXMLParams(self, CTNName = None):
        methode_name = os.path.join(self.CTNPath(CTNName), "methods.py")
        if os.path.isfile(methode_name):
            execfile(methode_name)
        
        # Get the base xml tree
        if self.MandatoryParams:
            try:
                basexmlfile = open(self.ConfNodeBaseXmlFilePath(CTNName), 'r')
                basetree = minidom.parse(basexmlfile)
                self.MandatoryParams[1].loadXMLTree(basetree.childNodes[0])
                basexmlfile.close()
            except Exception, exc:
                self.GetCTRoot().logger.write_error(_("Couldn't load confnode base parameters %s :\n %s") % (CTNName, str(exc)))
                self.GetCTRoot().logger.write_error(traceback.format_exc())
        
        # Get the xml tree
        if self.CTNParams:
            try:
                xmlfile = open(self.ConfNodeXmlFilePath(CTNName), 'r')
                tree = minidom.parse(xmlfile)
                self.CTNParams[1].loadXMLTree(tree.childNodes[0])
                xmlfile.close()
            except Exception, exc:
                self.GetCTRoot().logger.write_error(_("Couldn't load confnode parameters %s :\n %s") % (CTNName, str(exc)))
                self.GetCTRoot().logger.write_error(traceback.format_exc())
        
    def LoadChildren(self):
        # Iterate over all CTNName@CTNType in confnode directory, and try to open them
        for CTNDir in os.listdir(self.CTNPath()):
            if os.path.isdir(os.path.join(self.CTNPath(), CTNDir)) and \
               CTNDir.count(NameTypeSeparator) == 1:
                pname, ptype = CTNDir.split(NameTypeSeparator)
                try:
                    self.CTNAddChild(pname, ptype)
                except Exception, exc:
                    self.GetCTRoot().logger.write_error(_("Could not add child \"%s\", type %s :\n%s\n")%(pname, ptype, str(exc)))
                    self.GetCTRoot().logger.write_error(traceback.format_exc())

    def EnableMethod(self, method, value):
        for d in self.ConfNodeMethods:
            if d["method"]==method:
                d["enabled"]=value
                return True
        return False

    def ShowMethod(self, method, value):
        for d in self.ConfNodeMethods:
            if d["method"]==method:
                d["shown"]=value
                return True
        return False

    def CallMethod(self, method):
        for d in self.ConfNodeMethods:
            if d["method"]==method and d.get("enabled", True) and d.get("shown", True):
                getattr(self, method)()

def _GetClassFunction(name):
    def GetRootClass():
        return getattr(__import__("confnodes." + name), name).RootClass
    return GetRootClass


####################################################################################
####################################################################################
####################################################################################
###################################   ROOT    ######################################
####################################################################################
####################################################################################
####################################################################################

if wx.Platform == '__WXMSW__':
    exe_ext=".exe"
else:
    exe_ext=""

# import for project creation timestamping
from threading import Timer, Lock, Thread, Semaphore
from time import localtime
from datetime import datetime
# import necessary stuff from PLCOpenEditor
from PLCOpenEditor import PLCOpenEditor, ProjectDialog
from TextViewer import TextViewer
from plcopen.structures import IEC_KEYWORDS, TypeHierarchy_list


import re, tempfile
import targets
from targets.typemapping import DebugTypesSize

import connectors
from discovery import DiscoveryDialog
from weakref import WeakKeyDictionary

MATIEC_ERROR_MODEL = re.compile(".*\.st:(\d+)-(\d+)\.\.(\d+)-(\d+): error : (.*)$")

DEBUG_RETRIES_WARN = 3
DEBUG_RETRIES_REREGISTER = 4

class ConfigTreeRoot(ConfigTreeNode, PLCControler):
    """
    This class define Root object of the confnode tree. 
    It is responsible of :
    - Managing project directory
    - Building project
    - Handling PLCOpenEditor controler and view
    - Loading user confnodes and instanciante them as children
    - ...
    
    """

    # For root object, available Children Types are modules of the confnode packages.
    CTNChildrenTypes = [(name, _GetClassFunction(name), help) for name, help in zip(confnodes.__all__,confnodes.helps)]

    XSD = """<?xml version="1.0" encoding="ISO-8859-1" ?>
    <xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">
      <xsd:element name="BeremizRoot">
        <xsd:complexType>
          <xsd:sequence>
            <xsd:element name="TargetType">
              <xsd:complexType>
                <xsd:choice minOccurs="0">
                """+targets.targetchoices+"""
                </xsd:choice>
              </xsd:complexType>
            </xsd:element>
          </xsd:sequence>
          <xsd:attribute name="URI_location" type="xsd:string" use="optional" default=""/>
          <xsd:attribute name="Enable_ConfNodes" type="xsd:boolean" use="optional" default="true"/>
        </xsd:complexType>
      </xsd:element>
    </xsd:schema>
    """

    def __init__(self, frame, logger):
        PLCControler.__init__(self)

        self.MandatoryParams = None
        self.SetAppFrame(frame, logger)
        self._builder = None
        self._connector = None
        
        self.iec2c_path = os.path.join(base_folder, "matiec", "iec2c"+exe_ext)
        self.ieclib_path = os.path.join(base_folder, "matiec", "lib")
        
        # Setup debug information
        self.IECdebug_datas = {}
        self.IECdebug_lock = Lock()

        self.DebugTimer=None
        self.ResetIECProgramsAndVariables()
        
        #This method are not called here... but in NewProject and OpenProject
        #self._AddParamsMembers()
        #self.Children = {}

        # In both new or load scenario, no need to save
        self.ChangesToSave = False
        # root have no parent
        self.CTNParent = None
        # Keep track of the confnode type name
        self.CTNType = "Beremiz"
        self.Children = {}
        # After __init__ root confnode is not valid
        self.ProjectPath = None
        self._setBuildPath(None)
        self.DebugThread = None
        self.debug_break = False
        self.previous_plcstate = None
        # copy ConfNodeMethods so that it can be later customized
        self.ConfNodeMethods = [dic.copy() for dic in self.ConfNodeMethods]
        self.LoadSTLibrary()

    def __del__(self):
        if self.DebugTimer:
            self.DebugTimer.cancel()
        self.KillDebugThread()

    def SetAppFrame(self, frame, logger):
        self.AppFrame = frame
        self.logger = logger
        self.StatusTimer = None
        
        if frame is not None:
            # Timer to pull PLC status
            ID_STATUSTIMER = wx.NewId()
            self.StatusTimer = wx.Timer(self.AppFrame, ID_STATUSTIMER)
            self.AppFrame.Bind(wx.EVT_TIMER, self.PullPLCStatusProc, self.StatusTimer)
        
            self.RefreshConfNodesBlockLists()

    def ResetAppFrame(self, logger):
        if self.AppFrame is not None:
            self.AppFrame.Unbind(wx.EVT_TIMER, self.StatusTimer)
            self.StatusTimer = None
            self.AppFrame = None
        
        self.logger = logger

    def ConfNodeLibraryFilePath(self):
        return os.path.join(os.path.split(__file__)[0], "pous.xml")

    def CTNTestModified(self):
         return self.ChangesToSave or not self.ProjectIsSaved()

    def CTNFullName(self):
        return ""

    def GetCTRoot(self):
        return self

    def GetIECLibPath(self):
        return self.ieclib_path
    
    def GetIEC2cPath(self):
        return self.iec2c_path
    
    def GetCurrentLocation(self):
        return ()

    def GetCurrentName(self):
        return ""
    
    def _GetCurrentName(self):
        return ""

    def GetProjectPath(self):
        return self.ProjectPath

    def GetProjectName(self):
        return os.path.split(self.ProjectPath)[1]
    
    def GetDefaultTargetName(self):
        if wx.Platform == '__WXMSW__':
            return "Win32"
        else:
            return "Linux"

    def GetTarget(self):
        target = self.BeremizRoot.getTargetType()
        if target.getcontent() is None:
            target = self.Classes["BeremizRoot_TargetType"]()
            target_name = self.GetDefaultTargetName()
            target.setcontent({"name": target_name, "value": self.Classes["TargetType_%s"%target_name]()})
        return target
    
    def GetParamsAttributes(self, path = None):
        params = ConfigTreeNode.GetParamsAttributes(self, path)
        if params[0]["name"] == "BeremizRoot":
            for child in params[0]["children"]:
                if child["name"] == "TargetType" and child["value"] == '':
                    child.update(self.GetTarget().getElementInfos("TargetType")) 
        return params
        
    def SetParamsAttribute(self, path, value):
        if path.startswith("BeremizRoot.TargetType.") and self.BeremizRoot.getTargetType().getcontent() is None:
            self.BeremizRoot.setTargetType(self.GetTarget())
        return ConfigTreeNode.SetParamsAttribute(self, path, value)
        
    # helper func to check project path write permission
    def CheckProjectPathPerm(self, dosave=True):
        if CheckPathPerm(self.ProjectPath):
            return True
        dialog = wx.MessageDialog(self.AppFrame, 
                    _('You must have permission to work on the project\nWork on a project copy ?'),
                    _('Error'), 
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        answer = dialog.ShowModal()
        dialog.Destroy()
        if answer == wx.ID_YES:
            if self.SaveProjectAs():
                self.AppFrame.RefreshAll()
                self.AppFrame.RefreshTitle()
                self.AppFrame.RefreshFileMenu()
                return True
        return False
    
    def NewProject(self, ProjectPath, BuildPath=None):
        """
        Create a new project in an empty folder
        @param ProjectPath: path of the folder where project have to be created
        @param PLCParams: properties of the PLCOpen program created
        """
        # Verify that chosen folder is empty
        if not os.path.isdir(ProjectPath) or len(os.listdir(ProjectPath)) > 0:
            return _("Chosen folder isn't empty. You can't use it for a new project!")
        
        dialog = ProjectDialog(self.AppFrame)
        if dialog.ShowModal() == wx.ID_OK:
            values = dialog.GetValues()
            values["creationDateTime"] = datetime(*localtime()[:6])
            dialog.Destroy()
        else:
            dialog.Destroy()
            return _("Project not created")
        
        # Create PLCOpen program
        self.CreateNewProject(values)
        # Change XSD into class members
        self._AddParamsMembers()
        self.Children = {}
        # Keep track of the root confnode (i.e. project path)
        self.ProjectPath = ProjectPath
        self._setBuildPath(BuildPath)
        # get confnodes bloclist (is that usefull at project creation?)
        self.RefreshConfNodesBlockLists()
        # this will create files base XML files
        self.SaveProject()
        return None
        
    def LoadProject(self, ProjectPath, BuildPath=None):
        """
        Load a project contained in a folder
        @param ProjectPath: path of the project folder
        """
        if os.path.basename(ProjectPath) == "":
            ProjectPath = os.path.dirname(ProjectPath)
		# Verify that project contains a PLCOpen program
        plc_file = os.path.join(ProjectPath, "plc.xml")
        if not os.path.isfile(plc_file):
            return _("Chosen folder doesn't contain a program. It's not a valid project!")
        # Load PLCOpen file
        result = self.OpenXMLFile(plc_file)
        if result:
            return result
        # Change XSD into class members
        self._AddParamsMembers()
        self.Children = {}
        # Keep track of the root confnode (i.e. project path)
        self.ProjectPath = ProjectPath
        self._setBuildPath(BuildPath)
        # If dir have already be made, and file exist
        if os.path.isdir(self.CTNPath()) and os.path.isfile(self.ConfNodeXmlFilePath()):
            #Load the confnode.xml file into parameters members
            result = self.LoadXMLParams()
            if result:
                return result
            #Load and init all the children
            self.LoadChildren()
        self.RefreshConfNodesBlockLists()
        
        if os.path.exists(self._getBuildPath()):
            self.EnableMethod("_Clean", True)

        if os.path.isfile(self._getIECrawcodepath()):
            self.ShowMethod("_showIECcode", True)

        return None
    
    def CloseProject(self):
        self.ClearChildren()
        self.ResetAppFrame(None)
        
    def SaveProject(self):
        if self.CheckProjectPathPerm(False):
            self.SaveXMLFile(os.path.join(self.ProjectPath, 'plc.xml'))
            result = self.CTNRequestSave()
            if result:
                self.logger.write_error(result)
    
    def SaveProjectAs(self, dosave=True):
        # Ask user to choose a path with write permissions
        if wx.Platform == '__WXMSW__':
            path = os.getenv("USERPROFILE")
        else:
            path = os.getenv("HOME")
        dirdialog = wx.DirDialog(self.AppFrame , _("Choose a directory to save project"), path, wx.DD_NEW_DIR_BUTTON)
        answer = dirdialog.ShowModal()
        dirdialog.Destroy()
        if answer == wx.ID_OK:
            newprojectpath = dirdialog.GetPath()
            if os.path.isdir(newprojectpath):
                self.ProjectPath = newprojectpath
                if dosave:
                    self.SaveProject()
                self._setBuildPath(self.BuildPath)
                return True
        return False
    
    # Update PLCOpenEditor ConfNode Block types from loaded confnodes
    def RefreshConfNodesBlockLists(self):
        if getattr(self, "Children", None) is not None:
            self.ClearConfNodeTypes()
            self.AddConfNodeTypesList(self.ConfNodesTypesFactory())
        if self.AppFrame is not None:
            self.AppFrame.RefreshLibraryPanel()
            self.AppFrame.RefreshEditor()
    
    # Update a PLCOpenEditor Pou variable location
    def UpdateProjectVariableLocation(self, old_leading, new_leading):
        self.Project.updateElementAddress(old_leading, new_leading)
        self.BufferProject()
        if self.AppFrame is not None:
            self.AppFrame.RefreshTitle()
            self.AppFrame.RefreshInstancesTree()
            self.AppFrame.RefreshFileMenu()
            self.AppFrame.RefreshEditMenu()
            self.AppFrame.RefreshEditor()
    
    def GetVariableLocationTree(self):
        '''
        This function is meant to be overridden by confnodes.

        It should returns an list of dictionaries
        
        - IEC_type is an IEC type like BOOL/BYTE/SINT/...
        - location is a string of this variable's location, like "%IX0.0.0"
        '''
        children = []
        for child in self.IECSortedChildren():
            children.append(child.GetVariableLocationTree())
        return children
    
    def ConfNodePath(self):
        return os.path.join(os.path.split(__file__)[0], "confnodes")
    
    def CTNPath(self, CTNName=None):
        return self.ProjectPath
    
    def ConfNodeXmlFilePath(self, CTNName=None):
        return os.path.join(self.CTNPath(CTNName), "beremiz.xml")

    def ParentsTypesFactory(self):
        return self.ConfNodeTypesFactory()

    def _setBuildPath(self, buildpath):
        if CheckPathPerm(buildpath):
            self.BuildPath = buildpath
        else:
            self.BuildPath = None
        self.BuildPath = buildpath
        self.DefaultBuildPath = None
        if self._builder is not None:
            self._builder.SetBuildPath(self._getBuildPath())

    def _getBuildPath(self):
        # BuildPath is defined by user
        if self.BuildPath is not None:
            return self.BuildPath
        # BuildPath isn't defined by user but already created by default
        if self.DefaultBuildPath is not None:
            return self.DefaultBuildPath
        # Create a build path in project folder if user has permissions
        if CheckPathPerm(self.ProjectPath):
            self.DefaultBuildPath = os.path.join(self.ProjectPath, "build")
        # Create a build path in temp folder
        else:
            self.DefaultBuildPath = os.path.join(tempfile.mkdtemp(), os.path.basename(self.ProjectPath), "build")
            
        if not os.path.exists(self.DefaultBuildPath):
            os.makedirs(self.DefaultBuildPath)
        return self.DefaultBuildPath
    
    def _getExtraFilesPath(self):
        return os.path.join(self._getBuildPath(), "extra_files")

    def _getIECcodepath(self):
        # define name for IEC code file
        return os.path.join(self._getBuildPath(), "plc.st")
    
    def _getIECgeneratedcodepath(self):
        # define name for IEC generated code file
        return os.path.join(self._getBuildPath(), "generated_plc.st")
    
    def _getIECrawcodepath(self):
        # define name for IEC raw code file
        return os.path.join(self.CTNPath(), "raw_plc.st")
    
    def GetLocations(self):
        locations = []
        filepath = os.path.join(self._getBuildPath(),"LOCATED_VARIABLES.h")
        if os.path.isfile(filepath):
            # IEC2C compiler generate a list of located variables : LOCATED_VARIABLES.h
            location_file = open(os.path.join(self._getBuildPath(),"LOCATED_VARIABLES.h"))
            # each line of LOCATED_VARIABLES.h declares a located variable
            lines = [line.strip() for line in location_file.readlines()]
            # This regular expression parses the lines genereated by IEC2C
            LOCATED_MODEL = re.compile("__LOCATED_VAR\((?P<IEC_TYPE>[A-Z]*),(?P<NAME>[_A-Za-z0-9]*),(?P<DIR>[QMI])(?:,(?P<SIZE>[XBWDL]))?,(?P<LOC>[,0-9]*)\)")
            for line in lines:
                # If line match RE, 
                result = LOCATED_MODEL.match(line)
                if result:
                    # Get the resulting dict
                    resdict = result.groupdict()
                    # rewrite string for variadic location as a tuple of integers
                    resdict['LOC'] = tuple(map(int,resdict['LOC'].split(',')))
                    # set located size to 'X' if not given 
                    if not resdict['SIZE']:
                        resdict['SIZE'] = 'X'
                    # finally store into located variable list
                    locations.append(resdict)
        return locations
        
    def _Generate_SoftPLC(self):
        """
        Generate SoftPLC ST/IL/SFC code out of PLCOpenEditor controller, and compile it with IEC2C
        @param buildpath: path where files should be created
        """

        # Update PLCOpenEditor ConfNode Block types before generate ST code
        self.RefreshConfNodesBlockLists()
        
        self.logger.write(_("Generating SoftPLC IEC-61131 ST/IL/SFC code...\n"))
        buildpath = self._getBuildPath()
        # ask PLCOpenEditor controller to write ST/IL/SFC code file
        program, errors, warnings = self.GenerateProgram(self._getIECgeneratedcodepath())
        if len(warnings) > 0:
            self.logger.write_warning(_("Warnings in ST/IL/SFC code generator :\n"))
            for warning in warnings:
                self.logger.write_warning("%s\n"%warning)
        if len(errors) > 0:
            # Failed !
            self.logger.write_error(_("Error in ST/IL/SFC code generator :\n%s\n")%errors[0])
            return False
        plc_file = open(self._getIECcodepath(), "w")
        # Add ST Library from confnodes
        plc_file.write(self.ConfNodesSTLibraryFactory())
        if os.path.isfile(self._getIECrawcodepath()):
            plc_file.write(open(self._getIECrawcodepath(), "r").read())
            plc_file.write("\n")
        plc_file.close()
        plc_file = open(self._getIECcodepath(), "r")
        self.ProgramOffset = 0
        for line in plc_file.xreadlines():
            self.ProgramOffset += 1
        plc_file.close()
        plc_file = open(self._getIECcodepath(), "a")
        plc_file.write(open(self._getIECgeneratedcodepath(), "r").read())
        plc_file.close()

        self.logger.write(_("Compiling IEC Program into C code...\n"))

        # Now compile IEC code into many C files
        # files are listed to stdout, and errors to stderr. 
        status, result, err_result = ProcessLogger(
               self.logger,
               "\"%s\" -f -I \"%s\" -T \"%s\" \"%s\""%(
                         self.iec2c_path,
                         self.ieclib_path, 
                         buildpath,
                         self._getIECcodepath()),
               no_stdout=True, no_stderr=True).spin()
        if status:
            # Failed !
            
            # parse iec2c's error message. if it contains a line number,
            # then print those lines from the generated IEC file.
            for err_line in err_result.split('\n'):
                self.logger.write_warning(err_line + "\n")

                m_result = MATIEC_ERROR_MODEL.match(err_line)
                if m_result is not None:
                    first_line, first_column, last_line, last_column, error = m_result.groups()
                    first_line, last_line = int(first_line), int(last_line)
                    
                    last_section = None
                    f = open(self._getIECcodepath())

                    for i, line in enumerate(f.readlines()):
                        i = i + 1
                        if line[0] not in '\t \r\n':
                            last_section = line

                        if first_line <= i <= last_line:
                            if last_section is not None:
                                self.logger.write_warning("In section: " + last_section)
                                last_section = None # only write section once
                            self.logger.write_warning("%04d: %s" % (i, line))

                    f.close()
            
            self.logger.write_error(_("Error : IEC to C compiler returned %d\n")%status)
            return False
        
        # Now extract C files of stdout
        C_files = [ fname for fname in result.splitlines() if fname[-2:]==".c" or fname[-2:]==".C" ]
        # remove those that are not to be compiled because included by others
        C_files.remove("POUS.c")
        if not C_files:
            self.logger.write_error(_("Error : At least one configuration and one resource must be declared in PLC !\n"))
            return False
        # transform those base names to full names with path
        C_files = map(lambda filename:os.path.join(buildpath, filename), C_files)
        self.logger.write(_("Extracting Located Variables...\n"))
        # Keep track of generated located variables for later use by self._Generate_C
        self.PLCGeneratedLocatedVars = self.GetLocations()
        # Keep track of generated C files for later use by self.CTNGenerate_C
        self.PLCGeneratedCFiles = C_files
        # compute CFLAGS for plc
        self.plcCFLAGS = "\"-I"+self.ieclib_path+"\""
        return True

    def GetBuilder(self):
        """
        Return a Builder (compile C code into machine code)
        """
        # Get target, module and class name
        targetname = self.GetTarget().getcontent()["name"]
        modulename = "targets." + targetname
        classname = targetname + "_target"

        # Get module reference
        try :
            targetmodule = getattr(__import__(modulename), targetname)

        except Exception, msg:
            self.logger.write_error(_("Can't find module for target %s!\n")%targetname)
            self.logger.write_error(str(msg))
            return None
        
        # Get target class
        targetclass = getattr(targetmodule, classname)

        # if target already 
        if self._builder is None or not isinstance(self._builder,targetclass):
            # Get classname instance
            self._builder = targetclass(self)
        return self._builder

    def ResetBuildMD5(self):
        builder=self.GetBuilder()
        if builder is not None:
            builder.ResetBinaryCodeMD5()
        self.EnableMethod("_Transfer", False)

    def GetLastBuildMD5(self):
        builder=self.GetBuilder()
        if builder is not None:
            return builder.GetBinaryCodeMD5()
        else:
            return None

    #######################################################################
    #
    #                C CODE GENERATION METHODS
    #
    #######################################################################
    
    def CTNGenerate_C(self, buildpath, locations):
        """
        Return C code generated by iec2c compiler 
        when _generate_softPLC have been called
        @param locations: ignored
        @return: [(C_file_name, CFLAGS),...] , LDFLAGS_TO_APPEND
        """

        return ([(C_file_name, self.plcCFLAGS) 
                for C_file_name in self.PLCGeneratedCFiles ], 
               "", # no ldflags
               False) # do not expose retreive/publish calls
    
    def ResetIECProgramsAndVariables(self):
        """
        Reset variable and program list that are parsed from
        CSV file generated by IEC2C compiler.
        """
        self._ProgramList = None
        self._VariablesList = None
        self._IECPathToIdx = {}
        self._Ticktime = 0
        self.TracedIECPath = []

    def GetIECProgramsAndVariables(self):
        """
        Parse CSV-like file  VARIABLES.csv resulting from IEC2C compiler.
        Each section is marked with a line staring with '//'
        list of all variables used in various POUs
        """
        if self._ProgramList is None or self._VariablesList is None:
            try:
                csvfile = os.path.join(self._getBuildPath(),"VARIABLES.csv")
                # describes CSV columns
                ProgramsListAttributeName = ["num", "C_path", "type"]
                VariablesListAttributeName = ["num", "vartype", "IEC_path", "C_path", "type"]
                self._ProgramList = []
                self._VariablesList = []
                self._IECPathToIdx = {}
                
                # Separate sections
                ListGroup = []
                for line in open(csvfile,'r').xreadlines():
                    strippedline = line.strip()
                    if strippedline.startswith("//"):
                        # Start new section
                        ListGroup.append([])
                    elif len(strippedline) > 0 and len(ListGroup) > 0:
                        # append to this section
                        ListGroup[-1].append(strippedline)
        
                # first section contains programs
                for line in ListGroup[0]:
                    # Split and Maps each field to dictionnary entries
                    attrs = dict(zip(ProgramsListAttributeName,line.strip().split(';')))
                    # Truncate "C_path" to remove conf an ressources names
                    attrs["C_path"] = '__'.join(attrs["C_path"].split(".",2)[1:])
                    # Push this dictionnary into result.
                    self._ProgramList.append(attrs)
        
                # second section contains all variables
                for line in ListGroup[1]:
                    # Split and Maps each field to dictionnary entries
                    attrs = dict(zip(VariablesListAttributeName,line.strip().split(';')))
                    # Truncate "C_path" to remove conf an ressources names
                    parts = attrs["C_path"].split(".",2)
                    if len(parts) > 2:
                        attrs["C_path"] = '__'.join(parts[1:])
                    else:
                        attrs["C_path"] = '__'.join(parts)
                    # Push this dictionnary into result.
                    self._VariablesList.append(attrs)
                    # Fill in IEC<->C translation dicts
                    IEC_path=attrs["IEC_path"]
                    Idx=int(attrs["num"])
                    self._IECPathToIdx[IEC_path]=(Idx, attrs["type"])
                
                # third section contains ticktime
                if len(ListGroup) > 2:
                    self._Ticktime = int(ListGroup[2][0]) 
                
            except Exception,e:
                self.logger.write_error(_("Cannot open/parse VARIABLES.csv!\n"))
                self.logger.write_error(traceback.format_exc())
                self.ResetIECProgramsAndVariables()
                return False

        return True

    def Generate_plc_debugger(self):
        """
        Generate trace/debug code out of PLC variable list
        """
        self.GetIECProgramsAndVariables()

        # prepare debug code
        debug_code = targets.code("plc_debug") % {
           "buffer_size": reduce(lambda x, y: x + y, [DebugTypesSize.get(v["type"], 0) for v in self._VariablesList], 0),
           "programs_declarations":
               "\n".join(["extern %(type)s %(C_path)s;"%p for p in self._ProgramList]),
           "extern_variables_declarations":"\n".join([
              {"EXT":"extern __IEC_%(type)s_p %(C_path)s;",
               "IN":"extern __IEC_%(type)s_p %(C_path)s;",
               "MEM":"extern __IEC_%(type)s_p %(C_path)s;",
               "OUT":"extern __IEC_%(type)s_p %(C_path)s;",
               "VAR":"extern __IEC_%(type)s_t %(C_path)s;"}[v["vartype"]]%v 
               for v in self._VariablesList if v["vartype"] != "FB" and v["C_path"].find('.')<0]),
           "for_each_variable_do_code":"\n".join([
               {"EXT":"    (*fp)((void*)&%(C_path)s,%(type)s_P_ENUM);\n",
                "IN":"    (*fp)((void*)&%(C_path)s,%(type)s_P_ENUM);\n",
                "MEM":"    (*fp)((void*)&%(C_path)s,%(type)s_O_ENUM);\n",
                "OUT":"    (*fp)((void*)&%(C_path)s,%(type)s_O_ENUM);\n",
                "VAR":"    (*fp)((void*)&%(C_path)s,%(type)s_ENUM);\n"}[v["vartype"]]%v
                for v in self._VariablesList if v["vartype"] != "FB" and v["type"] in DebugTypesSize ]),
           "find_variable_case_code":"\n".join([
               "    case %(num)s:\n"%v+
               "        *varp = (void*)&%(C_path)s;\n"%v+
               {"EXT":"        return %(type)s_P_ENUM;\n",
                "IN":"        return %(type)s_P_ENUM;\n",
                "MEM":"        return %(type)s_O_ENUM;\n",
                "OUT":"        return %(type)s_O_ENUM;\n",
                "VAR":"        return %(type)s_ENUM;\n"}[v["vartype"]]%v
                for v in self._VariablesList if v["vartype"] != "FB" and v["type"] in DebugTypesSize ])}
        
        return debug_code
        
    def Generate_plc_common_main(self):
        """
        Use confnodes layout given in LocationCFilesAndCFLAGS to
        generate glue code that dispatch calls to all confnodes
        """
        # filter location that are related to code that will be called
        # in retreive, publish, init, cleanup
        locstrs = map(lambda x:"_".join(map(str,x)),
           [loc for loc,Cfiles,DoCalls in self.LocationCFilesAndCFLAGS if loc and DoCalls])

        # Generate main, based on template
        if self.BeremizRoot.getEnable_ConfNodes():
            plc_main_code = targets.code("plc_common_main") % {
                "calls_prototypes":"\n".join([(
                      "int __init_%(s)s(int argc,char **argv);\n"+
                      "void __cleanup_%(s)s(void);\n"+
                      "void __retrieve_%(s)s(void);\n"+
                      "void __publish_%(s)s(void);")%{'s':locstr} for locstr in locstrs]),
                "retrieve_calls":"\n    ".join([
                      "__retrieve_%s();"%locstrs[i-1] for i in xrange(len(locstrs), 0, -1)]),
                "publish_calls":"\n    ".join([ #Call publish in reverse order
                      "__publish_%s();"%locstr for locstr in locstrs]),
                "init_calls":"\n    ".join([
                      "init_level=%d; "%(i+1)+
                      "if((res = __init_%s(argc,argv))){"%locstr +
                      #"printf(\"%s\"); "%locstr + #for debug
                      "return res;}" for i,locstr in enumerate(locstrs)]),
                "cleanup_calls":"\n    ".join([
                      "if(init_level >= %d) "%i+
                      "__cleanup_%s();"%locstrs[i-1] for i in xrange(len(locstrs), 0, -1)])
                }
        else:
            plc_main_code = targets.code("plc_common_main") % {
                "calls_prototypes":"\n",
                "retrieve_calls":"\n",
                "publish_calls":"\n",
                "init_calls":"\n",
                "cleanup_calls":"\n"
                }
        plc_main_code += targets.targetcode(self.GetTarget().getcontent()["name"])
        return plc_main_code

        
    def _Build(self):
        """
        Method called by user to (re)build SoftPLC and confnode tree
        """
        if self.AppFrame is not None:
            self.AppFrame.ClearErrors()
        
        buildpath = self._getBuildPath()

        # Eventually create build dir
        if not os.path.exists(buildpath):
            os.mkdir(buildpath)
        # There is something to clean
        self.EnableMethod("_Clean", True)

        self.logger.flush()
        self.logger.write(_("Start build in %s\n") % buildpath)

        # Generate SoftPLC IEC code
        IECGenRes = self._Generate_SoftPLC()
        self.ShowMethod("_showIECcode", True)

        # If IEC code gen fail, bail out.
        if not IECGenRes:
            self.logger.write_error(_("IEC-61131-3 code generation failed !\n"))
            self.ResetBuildMD5()
            return False

        # Reset variable and program list that are parsed from
        # CSV file generated by IEC2C compiler.
        self.ResetIECProgramsAndVariables()
        
        # Generate C code and compilation params from confnode hierarchy
        self.logger.write(_("Generating confnodes C code\n"))
        try:
            self.LocationCFilesAndCFLAGS, self.LDFLAGS, ExtraFiles = self._Generate_C(
                buildpath, 
                self.PLCGeneratedLocatedVars)
        except Exception, exc:
            self.logger.write_error(_("ConfNodes code generation failed !\n"))
            self.logger.write_error(traceback.format_exc())
            self.ResetBuildMD5()
            return False

        # Get temporary directory path
        extrafilespath = self._getExtraFilesPath()
        # Remove old directory
        if os.path.exists(extrafilespath):
            shutil.rmtree(extrafilespath)
        # Recreate directory
        os.mkdir(extrafilespath)
        # Then write the files
        for fname,fobject in ExtraFiles:
            fpath = os.path.join(extrafilespath,fname)
            open(fpath, "wb").write(fobject.read())
        # Now we can forget ExtraFiles (will close files object)
        del ExtraFiles
        
        # Template based part of C code generation
        # files are stacked at the beginning, as files of confnode tree root
        for generator, filename, name in [
           # debugger code
           (self.Generate_plc_debugger, "plc_debugger.c", "Debugger"),
           # init/cleanup/retrieve/publish, run and align code
           (self.Generate_plc_common_main,"plc_common_main.c","Common runtime")]:
            try:
                # Do generate
                code = generator()
                if code is None:
                     raise
                code_path = os.path.join(buildpath,filename)
                open(code_path, "w").write(code)
                # Insert this file as first file to be compiled at root confnode
                self.LocationCFilesAndCFLAGS[0][1].insert(0,(code_path, self.plcCFLAGS))
            except Exception, exc:
                self.logger.write_error(name+_(" generation failed !\n"))
                self.logger.write_error(traceback.format_exc())
                self.ResetBuildMD5()
                return False

        self.logger.write(_("C code generated successfully.\n"))

        # Get current or fresh builder
        builder = self.GetBuilder()
        if builder is None:
            self.logger.write_error(_("Fatal : cannot get builder.\n"))
            self.ResetBuildMD5()
            return False

        # Build
        try:
            if not builder.build() :
                self.logger.write_error(_("C Build failed.\n"))
                return False
        except Exception, exc:
            self.logger.write_error(_("C Build crashed !\n"))
            self.logger.write_error(traceback.format_exc())
            self.ResetBuildMD5()
            return False

        self.logger.write(_("Successfully built.\n"))
        # Update GUI status about need for transfer
        self.CompareLocalAndRemotePLC()
        return True
    
    def ShowError(self, logger, from_location, to_location):
        chunk_infos = self.GetChunkInfos(from_location, to_location)
        for infos, (start_row, start_col) in chunk_infos:
            start = (from_location[0] - start_row, from_location[1] - start_col)
            end = (to_location[0] - start_row, to_location[1] - start_col)
            #print from_location, to_location, start_row, start_col, start, end
            if self.AppFrame is not None:
                self.AppFrame.ShowError(infos, start, end)

    def _showIECcode(self):
        self._OpenView("IEC code")

    def _editIECrawcode(self):
        self._OpenView("IEC raw code")

    def _OpenView(self, name=None):
        if name == "IEC code":
            plc_file = self._getIECcodepath()
        
            IEC_code_viewer = TextViewer(self.AppFrame.TabsOpened, "", None, None, instancepath=name)
            #IEC_code_viewer.Enable(False)
            IEC_code_viewer.SetTextSyntax("ALL")
            IEC_code_viewer.SetKeywords(IEC_KEYWORDS)
            try:
                text = file(plc_file).read()
            except:
                text = '(* No IEC code have been generated at that time ! *)'
            IEC_code_viewer.SetText(text = text)
            IEC_code_viewer.SetIcon(self.AppFrame.GenerateBitmap("ST"))
                
            self.AppFrame.EditProjectElement(IEC_code_viewer, name)
            
            return IEC_code_viewer
        
        elif name == "IEC raw code":
            controler = MiniTextControler(self._getIECrawcodepath())
            IEC_raw_code_viewer = TextViewer(self.AppFrame.TabsOpened, "", None, controler, instancepath=name)
            #IEC_raw_code_viewer.Enable(False)
            IEC_raw_code_viewer.SetTextSyntax("ALL")
            IEC_raw_code_viewer.SetKeywords(IEC_KEYWORDS)
            IEC_raw_code_viewer.RefreshView()
            IEC_raw_code_viewer.SetIcon(self.AppFrame.GenerateBitmap("ST"))
                
            self.AppFrame.EditProjectElement(IEC_raw_code_viewer, name)

            return IEC_raw_code_viewer
        
        return None

    def _Clean(self):
        if os.path.isdir(os.path.join(self._getBuildPath())):
            self.logger.write(_("Cleaning the build directory\n"))
            shutil.rmtree(os.path.join(self._getBuildPath()))
        else:
            self.logger.write_error(_("Build directory already clean\n"))
        self.ShowMethod("_showIECcode", False)
        self.EnableMethod("_Clean", False)
        # kill the builder
        self._builder = None
        self.CompareLocalAndRemotePLC()

    ############# Real PLC object access #############
    def UpdateMethodsFromPLCStatus(self):
        # Get PLC state : Running or Stopped
        # TODO : use explicit status instead of boolean
        status = None
        if self._connector is not None:
            status = self._connector.GetPLCstatus()
        if status is None:
            self._connector = None
            status = "Disconnected"
        if(self.previous_plcstate != status):
            for args in {
                     "Started" :     [("_Run", False),
                                      ("_Stop", True)],
                     "Stopped" :     [("_Run", True),
                                      ("_Stop", False)],
                     "Empty" :       [("_Run", False),
                                      ("_Stop", False)],
                     "Broken" :      [],
                     "Disconnected" :[("_Run", False),
                                      ("_Stop", False),
                                      ("_Transfer", False),
                                      ("_Connect", True),
                                      ("_Disconnect", False)],
                   }.get(status,[]):
                self.ShowMethod(*args)
            self.previous_plcstate = status
            return True
        return False
    
    def PullPLCStatusProc(self, event):
        if self._connector is None:
            self.StatusTimer.Stop()
        if self.UpdateMethodsFromPLCStatus():
            
            status = _(self.previous_plcstate)
            {"Broken": self.logger.write_error,
             None: lambda x: None}.get(
                self.previous_plcstate, self.logger.write)(_("PLC is %s\n")%status)
            self.AppFrame.RefreshAll()
        
    def RegisterDebugVarToConnector(self):
        self.DebugTimer=None
        Idxs = []
        self.TracedIECPath = []
        if self._connector is not None:
            self.IECdebug_lock.acquire()
            IECPathsToPop = []
            for IECPath,data_tuple in self.IECdebug_datas.iteritems():
                WeakCallableDict, data_log, status, fvalue = data_tuple
                if len(WeakCallableDict) == 0:
                    # Callable Dict is empty.
                    # This variable is not needed anymore!
                    #print "Unused : " + IECPath
                    IECPathsToPop.append(IECPath)
                elif IECPath != "__tick__":
                    # Convert 
                    Idx, IEC_Type = self._IECPathToIdx.get(IECPath,(None,None))
                    if Idx is not None:
                        if IEC_Type in DebugTypesSize: 
                            Idxs.append((Idx, IEC_Type, fvalue, IECPath))
                        else:
                            self.logger.write_warning(_("Debug : Unsuppoted type to debug %s\n")%IEC_Type)
                    else:
                        self.logger.write_warning(_("Debug : Unknown variable %s\n")%IECPath)
            for IECPathToPop in IECPathsToPop:
                self.IECdebug_datas.pop(IECPathToPop)

            if Idxs:
                Idxs.sort()
                self.TracedIECPath = zip(*Idxs)[3]
                self._connector.SetTraceVariablesList(zip(*zip(*Idxs)[0:3]))
            else:
                self.TracedIECPath = []
                self._connector.SetTraceVariablesList([])
            self.IECdebug_lock.release()
            
            #for IEC_path, IECdebug_data in self.IECdebug_datas.iteritems():
            #    print IEC_path, IECdebug_data[0].keys()

    def ReArmDebugRegisterTimer(self):
        if self.DebugTimer is not None:
            self.DebugTimer.cancel()

        # Timer to prevent rapid-fire when registering many variables
        # use wx.CallAfter use keep using same thread. TODO : use wx.Timer instead
        self.DebugTimer=Timer(0.5,wx.CallAfter,args = [self.RegisterDebugVarToConnector])
        # Rearm anti-rapid-fire timer
        self.DebugTimer.start()

    def GetDebugIECVariableType(self, IECPath):
        Idx, IEC_Type = self._IECPathToIdx.get(IECPath,(None,None))
        return IEC_Type
        
    def SubscribeDebugIECVariable(self, IECPath, callableobj, *args, **kwargs):
        """
        Dispatching use a dictionnary linking IEC variable paths
        to a WeakKeyDictionary linking 
        weakly referenced callables to optionnal args
        """
        if IECPath != "__tick__" and not self._IECPathToIdx.has_key(IECPath):
            return None
        
        self.IECdebug_lock.acquire()
        # If no entry exist, create a new one with a fresh WeakKeyDictionary
        IECdebug_data = self.IECdebug_datas.get(IECPath, None)
        if IECdebug_data is None:
            IECdebug_data  = [
                    WeakKeyDictionary(), # Callables
                    [],                  # Data storage [(tick, data),...]
                    "Registered",        # Variable status
                    None]                # Forced value
            self.IECdebug_datas[IECPath] = IECdebug_data
        
        IECdebug_data[0][callableobj]=(args, kwargs)

        self.IECdebug_lock.release()
        
        self.ReArmDebugRegisterTimer()
        
        return IECdebug_data[1]

    def UnsubscribeDebugIECVariable(self, IECPath, callableobj):
        #print "Unsubscribe", IECPath, callableobj
        self.IECdebug_lock.acquire()
        IECdebug_data = self.IECdebug_datas.get(IECPath, None)
        if IECdebug_data is not None:
            IECdebug_data[0].pop(callableobj,None)
        self.IECdebug_lock.release()

        self.ReArmDebugRegisterTimer()

    def UnsubscribeAllDebugIECVariable(self):
        self.IECdebug_lock.acquire()
        IECdebug_data = {}
        self.IECdebug_lock.release()

        self.ReArmDebugRegisterTimer()

    def ForceDebugIECVariable(self, IECPath, fvalue):
        if not self.IECdebug_datas.has_key(IECPath):
            return
        
        self.IECdebug_lock.acquire()
        
        # If no entry exist, create a new one with a fresh WeakKeyDictionary
        IECdebug_data = self.IECdebug_datas.get(IECPath, None)
        IECdebug_data[2] = "Forced"
        IECdebug_data[3] = fvalue
        
        self.IECdebug_lock.release()
        
        self.ReArmDebugRegisterTimer()
    
    def ReleaseDebugIECVariable(self, IECPath):
        if not self.IECdebug_datas.has_key(IECPath):
            return
        
        self.IECdebug_lock.acquire()
        
        # If no entry exist, create a new one with a fresh WeakKeyDictionary
        IECdebug_data = self.IECdebug_datas.get(IECPath, None)
        IECdebug_data[2] = "Registered"
        IECdebug_data[3] = None
        
        self.IECdebug_lock.release()
        
        self.ReArmDebugRegisterTimer()
    
    def CallWeakcallables(self, IECPath, function_name, *cargs):
        data_tuple = self.IECdebug_datas.get(IECPath, None)
        if data_tuple is not None:
            WeakCallableDict, data_log, status, fvalue = data_tuple
            #data_log.append((debug_tick, value))
            for weakcallable,(args,kwargs) in WeakCallableDict.iteritems():
                #print weakcallable, value, args, kwargs
                function = getattr(weakcallable, function_name, None)
                if function is not None:
                    if status == "Forced" and cargs[1] == fvalue:
                        function(*(cargs + (True,) + args), **kwargs)
                    else:
                        function(*(cargs + args), **kwargs)
                # This will block thread if more than one call is waiting

    def GetTicktime(self):
        return self._Ticktime

    def RemoteExec(self, script, **kwargs):
        if self._connector is None:
            return -1, "No runtime connected!"
        return self._connector.RemoteExec(script, **kwargs)

    def DebugThreadProc(self):
        """
        This thread waid PLC debug data, and dispatch them to subscribers
        """
        self.debug_break = False
        debug_getvar_retry = 0
        while (not self.debug_break) and (self._connector is not None):
            Trace = self._connector.GetTraceVariables()
            if(Trace):
                plc_status, debug_tick, debug_vars = Trace
            else:
                plc_status = None
            debug_getvar_retry += 1
            #print debug_tick, debug_vars
            if plc_status == "Started":
                self.IECdebug_lock.acquire()
                if len(debug_vars) == len(self.TracedIECPath):
                    if debug_getvar_retry > DEBUG_RETRIES_WARN:
                        self.logger.write(_("... debugger recovered\n"))
                    debug_getvar_retry = 0
                    for IECPath,value in zip(self.TracedIECPath, debug_vars):
                        if value is not None:
                            self.CallWeakcallables(IECPath, "NewValue", debug_tick, value)
                    self.CallWeakcallables("__tick__", "NewDataAvailable")
                self.IECdebug_lock.release()
                if debug_getvar_retry == DEBUG_RETRIES_WARN:
                    self.logger.write(_("Waiting debugger to recover...\n"))
                if debug_getvar_retry == DEBUG_RETRIES_REREGISTER:
                    # re-register debug registry to PLC
                    wx.CallAfter(self.RegisterDebugVarToConnector)
                if debug_getvar_retry != 0:
                    # Be patient, tollerate PLC to come up before debugging
                    time.sleep(0.1)
            else:
                self.debug_break = True
        self.logger.write(_("Debugger disabled\n"))
        self.DebugThread = None

    def KillDebugThread(self):
        tmp_debugthread = self.DebugThread
        self.debug_break = True
        if tmp_debugthread is not None:
            self.logger.writeyield(_("Stopping debugger...\n"))
            tmp_debugthread.join(timeout=5)
            if tmp_debugthread.isAlive() and self.logger:
                self.logger.write_warning(_("Couldn't stop debugger.\n"))
            else:
                self.logger.write(_("Debugger stopped.\n"))
        self.DebugThread = None

    def _connect_debug(self): 
        if self.AppFrame:
            self.AppFrame.ResetGraphicViewers()
        self.RegisterDebugVarToConnector()
        if self.DebugThread is None:
            self.DebugThread = Thread(target=self.DebugThreadProc)
            self.DebugThread.start()
    
    def _Run(self):
        """
        Start PLC
        """
        if self.GetIECProgramsAndVariables():
            self._connector.StartPLC()
            self.logger.write(_("Starting PLC\n"))
            self._connect_debug()
        else:
            self.logger.write_error(_("Couldn't start PLC !\n"))
        wx.CallAfter(self.UpdateMethodsFromPLCStatus)
       
    def _Stop(self):
        """
        Stop PLC
        """
        if self._connector is not None and not self._connector.StopPLC():
            self.logger.write_error(_("Couldn't stop PLC !\n"))

        # debugthread should die on his own
        #self.KillDebugThread()
        
        wx.CallAfter(self.UpdateMethodsFromPLCStatus)

    def _Connect(self):
        # don't accept re-connetion is already connected
        if self._connector is not None:
            self.logger.write_error(_("Already connected. Please disconnect\n"))
            return
        
        # Get connector uri
        uri = self.\
              BeremizRoot.\
              getURI_location().\
              strip()

        # if uri is empty launch discovery dialog
        if uri == "":
            # Launch Service Discovery dialog
            dialog = DiscoveryDialog(self.AppFrame)
            answer = dialog.ShowModal()
            uri = dialog.GetURI()
            dialog.Destroy()
            
            # Nothing choosed or cancel button
            if uri is None or answer == wx.ID_CANCEL:
                self.logger.write_error(_("Connection canceled!\n"))
                return
            else:
                self.\
                BeremizRoot.\
                setURI_location(uri)
       
        # Get connector from uri
        try:
            self._connector = connectors.ConnectorFactory(uri, self)
        except Exception, msg:
            self.logger.write_error(_("Exception while connecting %s!\n")%uri)
            self.logger.write_error(traceback.format_exc())

        # Did connection success ?
        if self._connector is None:
            # Oups.
            self.logger.write_error(_("Connection failed to %s!\n")%uri)
        else:
            self.ShowMethod("_Connect", False)
            self.ShowMethod("_Disconnect", True)
            self.ShowMethod("_Transfer", True)

            self.CompareLocalAndRemotePLC()
            
            # Init with actual PLC status and print it
            self.UpdateMethodsFromPLCStatus()
            if self.previous_plcstate is not None:
                status = _(self.previous_plcstate)
            else:
                status = ""
            self.logger.write(_("PLC is %s\n")%status)
            
            # Start the status Timer
            self.StatusTimer.Start(milliseconds=500, oneShot=False)
            
            if self.previous_plcstate=="Started":
                if self.DebugAvailable() and self.GetIECProgramsAndVariables():
                    self.logger.write(_("Debug connect matching running PLC\n"))
                    self._connect_debug()
                else:
                    self.logger.write_warning(_("Debug do not match PLC - stop/transfert/start to re-enable\n"))

    def CompareLocalAndRemotePLC(self):
        if self._connector is None:
            return
        # We are now connected. Update button status
        MD5 = self.GetLastBuildMD5()
        # Check remote target PLC correspondance to that md5
        if MD5 is not None:
            if not self._connector.MatchMD5(MD5):
#                self.logger.write_warning(
#                   _("Latest build does not match with target, please transfer.\n"))
                self.EnableMethod("_Transfer", True)
            else:
#                self.logger.write(
#                   _("Latest build matches target, no transfer needed.\n"))
                self.EnableMethod("_Transfer", True)
                # warns controller that program match
                self.ProgramTransferred()
                #self.EnableMethod("_Transfer", False)
        else:
#            self.logger.write_warning(
#                _("Cannot compare latest build to target. Please build.\n"))
            self.EnableMethod("_Transfer", False)


    def _Disconnect(self):
        self._connector = None
        self.StatusTimer.Stop()
        wx.CallAfter(self.UpdateMethodsFromPLCStatus)
        
    def _Transfer(self):
        # Get the last build PLC's 
        MD5 = self.GetLastBuildMD5()
        
        # Check if md5 file is empty : ask user to build PLC 
        if MD5 is None :
            self.logger.write_error(_("Failed : Must build before transfer.\n"))
            return False

        # Compare PLC project with PLC on target
        if self._connector.MatchMD5(MD5):
            self.logger.write(
                _("Latest build already matches current target. Transfering anyway...\n"))

        # Get temprary directory path
        extrafilespath = self._getExtraFilesPath()
        extrafiles = [(name, open(os.path.join(extrafilespath, name), 
                                  'rb').read()) \
                      for name in os.listdir(extrafilespath) \
                      if not name=="CVS"]

        # Send PLC on target
        builder = self.GetBuilder()
        if builder is not None:
            data = builder.GetBinaryCode()
            if data is not None :
                if self._connector.NewPLC(MD5, data, extrafiles) and self.GetIECProgramsAndVariables():
                    self.UnsubscribeAllDebugIECVariable()
                    self.ProgramTransferred()
                    if self.AppFrame is not None:
                        self.AppFrame.RefreshInstancesTree()
                        self.AppFrame.CloseObsoleteDebugTabs()
                    self.logger.write(_("Transfer completed successfully.\n"))
                else:
                    self.logger.write_error(_("Transfer failed\n"))
            else:
                self.logger.write_error(_("No PLC to transfer (did build succeed ?)\n"))

        wx.CallAfter(self.UpdateMethodsFromPLCStatus)

    ConfNodeMethods = [
        {"bitmap" : opjimg("Build"),
         "name" : _("Build"),
         "tooltip" : _("Build project into build folder"),
         "method" : "_Build"},
        {"bitmap" : opjimg("Clean"),
         "name" : _("Clean"),
         "enabled" : False,
         "tooltip" : _("Clean project build folder"),
         "method" : "_Clean"},
        {"bitmap" : opjimg("Run"),
         "name" : _("Run"),
         "shown" : False,
         "tooltip" : _("Start PLC"),
         "method" : "_Run"},
        {"bitmap" : opjimg("Stop"),
         "name" : _("Stop"),
         "shown" : False,
         "tooltip" : _("Stop Running PLC"),
         "method" : "_Stop"},
        {"bitmap" : opjimg("Connect"),
         "name" : _("Connect"),
         "tooltip" : _("Connect to the target PLC"),
         "method" : "_Connect"},
        {"bitmap" : opjimg("Transfer"),
         "name" : _("Transfer"),
         "shown" : False,
         "tooltip" : _("Transfer PLC"),
         "method" : "_Transfer"},
        {"bitmap" : opjimg("Disconnect"),
         "name" : _("Disconnect"),
         "shown" : False,
         "tooltip" : _("Disconnect from PLC"),
         "method" : "_Disconnect"},
        {"bitmap" : opjimg("ShowIECcode"),
         "name" : _("Show code"),
         "shown" : False,
         "tooltip" : _("Show IEC code generated by PLCGenerator"),
         "method" : "_showIECcode"},
        {"bitmap" : opjimg("editIECrawcode"),
         "name" : _("Raw IEC code"),
         "tooltip" : _("Edit raw IEC code added to code generated by PLCGenerator"),
         "method" : "_editIECrawcode"},
    ]