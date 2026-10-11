package com.example.slowquery.service;

import com.example.slowquery.mapper.AuditEventMapper;
import com.example.slowquery.model.AuditEvent;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class AuditEventService {

    private final AuditEventMapper auditEventMapper;

    public AuditEventService(AuditEventMapper auditEventMapper) {
        this.auditEventMapper = auditEventMapper;
    }

    public List<AuditEvent> findByDay(String day, int limit) {
        return auditEventMapper.findByDay(day, limit);
    }
}
