#! -*- encoding:utf-8 -*-

import copy
import datetime
import hashlib
from django.db import models
from django.utils.functional import curry
from django.utils.translation import ugettext_lazy as _

from audit_log.models.fields import LastUserField

class LogEntryObjectDescriptor(object):
    def __init__(self, model):
        model._meta.local_many_to_many = []
        '''
        for field in model._meta.fields:# + model._meta.many_to_many:
            print field 
            #when these m2m field gets in here, it's already TextField.
            if isinstance(field, models.related.ManyToManyField):
                field.__class__ = models.TextField
            #    #mockup for m2m
            pass
        
        for field in model._meta.many_to_many:
            if isinstance(field, models.TextField):
                field.__class__ = models.related.ManyToManyField
        
        '''

        self.model = model

    def __get__(self, instance, owner):
        #values = (getattr(instance, f.attname) for f in self.model._meta.fields)
        #print [f.attname for f in self.model._meta.fields] #DEBUG: it seems we don't have any m2m fields here.

        for f in self.model._meta.fields + self.model._meta.many_to_many:
            print "get_field_value in LogEntryObjectDescriptor:", f
            if not isinstance(f, models.related.ManyToManyField):
                values.append(getattr(instance, f.attname))
            else:
                #M2M
                values.append(f.attname) #a mockup

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
            logentry1 = LogEntry_list[logentry_id]
            try:
                logentry2 = LogEntry_list[logentry_id+1]
            except:
                #There is no according record LogEntry to diff
                continue

            model1 = logentry1.object_state
            model2 = logentry2.object_state

            changes_header = {}
            changes_header['Modified'] = str(logentry1.action_date)
            changes_header['User'] = str(logentry1.action_user)
            changes_header['Type'] = str(logentry1.action_type)

            changes = {}
            excludes = ['edittime'] #should have a _meta.do_not_show_diff_field or something.
            #excludes = logentry1._exclude #programs terminates here.
            #print logentry1._exclude

            if changes_header['Type'].lower() == 'u': #if Changed
                
                #FIXME It seems that ManyToMany change logs still can not be tracked?
                field_joint  = model1._meta.fields + model1._meta.many_to_many

                for field in field_joint:
                    if not field.name in excludes:
                        if field.value_from_object(model1) != field.value_from_object(model2): #and \
                           #hashlib.md5(field.value_from_object(model1)).hexdigest() != hashlib.md5(field.value_from_object(model2)).hexdigest():
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

        #return [states_changed_info, diff_string]
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
        for field in instance._meta.fields + instance._meta.many_to_many:
            if field.attname not in self._exclude:
                if not isinstance(field, models.related.ManyToManyField):
                    attrs[field.attname] = getattr(instance, field.attname)
                else:
                    attrs[field.attname] = field.attname
                print field.attname #Still don't have m2m fields here.
        manager.create(action_type = action_type, **attrs)
    
    def post_save(self, instance, created, **kwargs):
        self.create_log_entry(instance, created and 'I' or 'U')
    
    
    def post_delete(self, instance, **kwargs):
        self.create_log_entry(instance,  'D')
    
    
    def finalize(self, sender, **kwargs):
        log_entry_model = self.create_log_entry_model(sender)
        models.signals.post_save.connect(self.post_save, sender = sender, weak = False)
        models.signals.post_delete.connect(self.post_delete, sender = sender, weak = False)
        # set the manager 
        descriptor = AuditLogDescriptor(log_entry_model, self.manager_class)
        setattr(sender, self.manager_name, descriptor)
    
    def copy_fields(self, model):
        """
        Creates copies of the fields we are keeping
        track of for the provided model, returning a 
        dictionary mapping field name to a copied field object.
        """
        fields = {'__module__' : model.__module__}

        recover_m2m_fields = model._meta.local_many_to_many
        #print recover_m2m_fields 

        for field in model._meta.fields + model._meta.many_to_many:
            
            #print "in copy_fields"
            #print field #it seems we don't have m2m field here either!

            if not field.name in self._exclude:
            
                if not isinstance(field, models.related.ManyToManyField):
                    
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

                else:
                    #print field.value_to_string()
                    #it processes only the model structure here, not the data
                    #therefore you can not get the obj/data here

                    #field2  = copy.copy(field)
                    #don't have to copy it. just created a new 
                    #replaced M2M Field with TextField here
                    field2 = models.TextField(blank=True)
                    field2.__class__ = models.TextField
                    field2.attname = field.attname
                    field2.name = field.name

                    #don't copy made a relief to handle the M2M relations.
                    #model._meta.many_to_many.remove(field)
                    #model._meta.local_many_to_many.remove(field2)
                    #field2.rel = None
                    #print model._meta.many_to_many
                    #print model._meta.local_many_to_many
                    #You have to remove these changed M2M field from local_many_to_many.
                    #And make sure field.rel = None
                    #Otherwise manager.py will still validate them as M2M

                    '''print dir(field)
                    tp = ['m2m_column_name', 'm2m_db_table', 'm2m_field_name', 'm2m_reverse_field_name','m2m_reverse_name']
                    for each in tp:
                        print getattr(field, each)#[each]
                        setattr(field,each,None)'''

                    #print field
                    fields[field2.name] = field2



        model._meta.local_many_to_many = recover_m2m_fields
        #print model._meta.many_to_many
        #del Tag._meta._all_related_many_to_many_objects

        #print dir(model._meta)
        
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
        #print attrs  #it seems there is not m2m fields either!
        
        return type(name, (models.Model,), attrs)
        
