package com.example.slowquery.service;

import com.example.slowquery.mapper.AuditLogMapper;
import com.example.slowquery.model.AuditLog;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class AuditLogService {

    private final AuditLogMapper auditLogMapper;

    public AuditLogService(AuditLogMapper auditLogMapper) {
        this.auditLogMapper = auditLogMapper;
    }

    public List<AuditLog> recentByLevel(String level, int limit) {
        return auditLogMapper.findRecentByLevel(level, limit);
    }
}
