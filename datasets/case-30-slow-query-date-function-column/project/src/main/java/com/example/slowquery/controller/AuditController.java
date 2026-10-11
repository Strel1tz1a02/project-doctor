package com.example.slowquery.controller;

import com.example.slowquery.model.AuditEvent;
import com.example.slowquery.service.AuditEventService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/audit")
public class AuditController {

    private final AuditEventService auditEventService;

    public AuditController(AuditEventService auditEventService) {
        this.auditEventService = auditEventService;
    }

    @GetMapping("/events/by-day")
    public List<AuditEvent> eventsByDay(@RequestParam(defaultValue = "2025-06-10") String day,
                                        @RequestParam(defaultValue = "20") int size) {
        return auditEventService.findByDay(day, size);
    }
}
