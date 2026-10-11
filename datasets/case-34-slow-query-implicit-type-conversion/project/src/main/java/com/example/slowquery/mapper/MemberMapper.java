package com.example.slowquery.mapper;

import com.example.slowquery.model.Member;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface MemberMapper {

    @Select(
        "SELECT id, member_no, nickname, level, created_at_ms " +
        "FROM members " +
        "WHERE member_no = #{memberNo}"
    )
    Member findByMemberNo(@Param("memberNo") long memberNo);
}
