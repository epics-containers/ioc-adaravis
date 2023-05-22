TOP = ../..
include $(TOP)/configure/CONFIG

PROD_IOC = ioc
DBD += ioc.dbd
ioc_DBD += base.dbd
ioc_DBD += devIocStats.dbd
ioc_DBD += asyn.dbd
ioc_DBD += busySupport.dbd
ioc_DBD += ADSupport.dbd
ioc_DBD += NDPluginSupport.dbd
ioc_DBD += NDFileHDF5.dbd
ioc_DBD += NDFileJPEG.dbd
ioc_DBD += NDFileTIFF.dbd
ioc_DBD += NDFileNull.dbd
ioc_DBD += NDPosPlugin.dbd
ioc_DBD += ADAravisSupport.dbd
ioc_DBD += PVAServerRegister.dbd
ioc_DBD += NDPluginPva.dbd
ioc_SRCS += ioc_registerRecordDeviceDriver.cpp
ioc_LIBS += ntndArrayConverter
ioc_LIBS += nt
ioc_LIBS += pvData
ioc_LIBS += pvDatabase
ioc_LIBS += pvAccessCA
ioc_LIBS += pvAccessIOC
ioc_LIBS += pvAccess
ioc_LIBS += ADAravis
ioc_LIBS += NDPlugin
ioc_LIBS += ADBase
ioc_LIBS += cbfad
ioc_LIBS += busy
ioc_LIBS += asyn
ioc_LIBS += devIocStats
ioc_LIBS += $(EPICS_BASE_IOC_LIBS)
ioc_SRCS += iocMain.cpp

ioc_SYS_LIBS += aravis-0.8

include $(TOP)/configure/RULES
