package com.example.slowquery.mapper;

import com.example.slowquery.model.AuditEvent;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface AuditEventMapper {

    @Select(
        "SELECT * " +
        "FROM audit_events " +
        "WHERE DATE(FROM_UNIXTIME(occurred_at_ms / 1000)) = #{day} " +
        "ORDER BY occurred_at_ms DESC " +
        "LIMIT #{limit}"
    )
    List<AuditEvent> findByDay(@Param("day") String day, @Param("limit") int limit);
}
