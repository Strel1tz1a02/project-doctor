package com.example.slowquery.mapper;

import com.example.slowquery.model.AuditLog;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface AuditLogMapper {

    @Select(
        "SELECT id, service_name, level, message, trace_id, created_at_ms " +
        "FROM audit_logs " +
        "WHERE level = #{level} " +
        "ORDER BY created_at_ms DESC " +
        "LIMIT #{limit}"
    )
    List<AuditLog> findRecentByLevel(@Param("level") String level, @Param("limit") int limit);
}
