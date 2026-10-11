package com.example.slowquery.controller;

import com.example.slowquery.model.AuditLog;
import com.example.slowquery.service.AuditLogService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/audit")
public class AuditLogController {

    private final AuditLogService auditLogService;

    public AuditLogController(AuditLogService auditLogService) {
        this.auditLogService = auditLogService;
    }

    @GetMapping("/recent")
    public List<AuditLog> recent(@RequestParam(defaultValue = "ERROR") String level,
                                 @RequestParam(defaultValue = "100") int limit) {
        return auditLogService.recentByLevel(level, limit);
    }
}
