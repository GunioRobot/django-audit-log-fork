#! -*- encoding:utf-8 -*-

import copy
import datetime
from django.db import models
from django.utils.functional import curry
from django.utils.translation import ugettext_lazy as _



from audit_log.models.fields import LastUserField

class LogEntryObjectDescriptor(object):
    def __init__(self, model):
        self.model = model
    
    def __get__(self, instance, owner):
        values = (getattr(instance, f.attname) for f in self.model._meta.fields)
        return self.model(*values)

class AuditLogManager(models.Manager):
    def __init__(self, model, instance = None):
        super(AuditLogManager, self).__init__()
        self.model = model
        self.instance = instance
    
    def get_query_set(self):
        if self.instance is None:
            return super(AuditLogManager, self).get_query_set()
        
        f = {self.instance._meta.pk.name : self.instance.pk}
        return super(AuditLogManager, self).get_query_set().filter(**f)
   
    def get_diff(self):
        '''Output the differences between LogEntries.'''

        if self.instance is None:
            LogEntry_list = super(AuditLogManager, self).get_query_set()
        else:
            f = {self.instance._meta.pk.name : self.instance.pk}
            LogEntry_list = super(AuditLogManager, self).get_query_set().filter(**f)
        
        diff_result = []

        for logentry_id in range(0,len(LogEntry_list)):
            print logentry_id 
            logentry1 = LogEntry_list[logentry_id]
            try:
                logentry2 = LogEntry_list[logentry_id+1]
            except:
                #There is no according record LogEntry to diff
                continue

            model1 = logentry1.object_state
            model2 = logentry2.object_state
            print model1.monitor.all()
            print model2.monitor.all()
            changes_header = {}
            changes_header['Modified'] = str(logentry1.action_date)
            changes_header['User'] = str(logentry1.action_user)
            changes_header['Type'] = str(logentry1.action_type)

            changes = {}
            excludes = ['edittime'] #should have a _meta.do_not_show_diff_field or something.

            if changes_header['Type'].lower() == 'u': #if Changed
                
                #FIXME It seems that ManyToMany change logs still can not be tracked?
                field_joint  = model1._meta.fields + model1._meta.many_to_many

                for field in field_joint:
                    if not field.name in excludes:
                        if field.value_from_object(model1) != field.value_from_object(model2) and \
                           str(field.value_from_object(model1)) != str(field.value_from_object(model2)):
                            try:
                                changes[field.verbose_name] = (field.value_from_object(model2).encode("utf-8"), \
                                                               field.value_from_object(model1).encode("utf-8"))
                            except:
                                changes[field.verbose_name] = (str(field.value_from_object(model2)), \
                                                               str(field.value_from_object(model1)))
            #producing diff string text                    
            try:
                context = ", ".join(map(lambda x:u"%(k)s:%(o)s->%(n)s" % {'k':x[0],'o':x[1][0],'n':x[1][1]}, changes.iteritems()))
            except:
                context = ", ".join(map(lambda x:u"%(k)s:%(o)s->%(n)s" % {'k':str(x[0]).decode("utf-8"),'o':str(x[1][0]).decode("utf-8"),'n':str(x[1][1]).decode("utf-8")}, changes.iteritems())) 

            diff_result.append([changes_header, context])

        return diff_result
            
class AuditLogDescriptor(object):
    def __init__(self, model, manager_class):
        self.model = model
        self._manager_class = manager_class
    
    def __get__(self, instance, owner):
        if instance is None:
            return self._manager_class(self.model)
        return self._manager_class(self.model, instance)

class AuditLog(object):
    
    manager_class = AuditLogManager
    
    def __init__(self, exclude = []):
        self._exclude = exclude
    
    def contribute_to_class(self, cls, name):
        self.manager_name = name
        models.signals.class_prepared.connect(self.finalize, sender = cls)
    
    
    def create_log_entry(self, instance, action_type):
        manager = getattr(instance, self.manager_name)
        attrs = {}
        for field in instance._meta.fields:
            if field.attname not in self._exclude:
                attrs[field.attname] = getattr(instance, field.attname)
        manager.create(action_type = action_type, **attrs)
    
    def post_save(self, instance, created, **kwargs):
        self.create_log_entry(instance, created and 'I' or 'U')
    
    
    def post_delete(self, instance, **kwargs):
        self.create_log_entry(instance,  'D')
    
    
    def finalize(self, sender, **kwargs):
        log_entry_model = self.create_log_entry_model(sender)
        
        models.signals.post_save.connect(self.post_save, sender = sender, weak = False)
        models.signals.post_delete.connect(self.post_delete, sender = sender, weak = False)
        
        descriptor = AuditLogDescriptor(log_entry_model, self.manager_class)
        setattr(sender, self.manager_name, descriptor)
    
    def copy_fields(self, model):
        """
        Creates copies of the fields we are keeping
        track of for the provided model, returning a 
        dictionary mapping field name to a copied field object.
        """
        fields = {'__module__' : model.__module__}
        
        for field in model._meta.fields:
            
            if not field.name in self._exclude:
                
                field  = copy.copy(field)
            
                if isinstance(field, models.AutoField):
                    #we replace the AutoField of the original model
                    #with an IntegerField because a model can
                    #have only one autofield.
                
                    field.__class__ = models.IntegerField
            
                if field.primary_key or field.unique:
                    #unique fields of the original model
                    #can not be guaranteed to be unique
                    #in the audit log entry but they
                    #should still be indexed for faster lookups.
                
                    field.primary_key = False
                    field._unique = False
                    field.db_index = True
            
                fields[field.name] = field
            
        return fields
    

    
    def get_logging_fields(self, model):
        """
        Returns a dictionary mapping of the fields that are used for
        keeping the acutal audit log entries.
        """
        rel_name = '_%s_audit_log_entry'%model._meta.object_name.lower()
        
        def entry_instance_to_unicode(log_entry):
            try:
                result = u'%s: %s %s at %s'%(model._meta.object_name, 
                                                log_entry.object_state, 
                                                log_entry.get_action_type_display().lower(),
                                                log_entry.action_date,
                                                
                                                )
            except AttributeError:
                result = u'%s %s at %s'%(model._meta.object_name,
                                                log_entry.get_action_type_display().lower(),
                                                log_entry.action_date
                                                
                                                )
            return result
        
        return {
            'action_id' : models.AutoField(primary_key = True),
            'action_date' : models.DateTimeField(default = datetime.datetime.now),
            'action_user' : LastUserField(related_name = rel_name),
            'action_type' : models.CharField(max_length = 1, choices = (
                ('I', _('Created')),
                ('U', _('Changed')),
                ('D', _('Deleted')),
            )),
            'object_state' : LogEntryObjectDescriptor(model),
            '__unicode__' : entry_instance_to_unicode,
        }
            
    
    def get_meta_options(self, model):
        """
        Returns a dictionary of fileds that will be added to
        the Meta inner class of the log entry model.
        """
        return {
            'ordering' : ('-action_date',),
            'app_label' : model._meta.app_label,
        }
    
    def create_log_entry_model(self, model):
        """
        Creates a log entry model that will be associated with
        the model provided.
        """
        
        attrs = self.copy_fields(model)
        attrs.update(self.get_logging_fields(model))
        attrs.update(Meta = type('Meta', (), self.get_meta_options(model)))
        name = '%sAuditLogEntry'%model._meta.object_name
        return type(name, (models.Model,), attrs)
        
