let page = 1
let loading = false
let hasMore = true
let show_img = true
let exists_only = false

let selectedTags = []
let tagElements = new Map()
let existingTags = []
let allTags = []
let allPublishes = []
let allAuthorTags = []
let editingItemId = null
let pendingDeleteId = null
let addTagsList = []
let editTagsList = []
let darkMode = false

function getWallColumns() {
    let wall = document.getElementById("wall")
    if (!wall) return 1
    let style = window.getComputedStyle(wall)
    let cols = style.gridTemplateColumns.split(" ").filter(x => x.trim()).length
    return cols > 0 ? cols : 1
}

function getPageSize() {
    if (!show_img) return 20
    let cols = getWallColumns()
    let approxCardHeight = 300
    let rows = Math.max(1, Math.ceil(window.innerHeight / approxCardHeight))
    return cols * rows
}

async function loadTags() {

    // 查询条件使用只在库标签
    let r = await fetch("/api/tags")
    existingTags = await r.json()

    // 新增/编辑时下拉提示使用全量标签
    let rAll = await fetch("/api/tags?include_all=1")
    allTags = await rAll.json()

    let div = document.getElementById("taglist")
    div.innerHTML = ""
    tagElements.clear()

    existingTags.forEach(t => {

        let e = document.createElement("span")

        e.className = "tag"
        if (selectedTags.includes(t)) {
            e.classList.add("selected")
        }

        e.innerText = t

        e.onclick = () => toggleTag(t, e)

        div.appendChild(e)
        tagElements.set(t, e)

    })

    updateTagDatalist()
    updateTagDatalistSimple("add_tags", "tag-options-add")
    updateTagDatalistSimple("edit_tags", "tag-options-edit")
}

async function loadPublishes() {

    let r = await fetch("/api/publishes")
    let payload = await r.json()
    let data = Array.isArray(payload) ? payload : (payload.items || [])
    let total = Array.isArray(payload) ? data.length : (payload.total || 0)
    allPublishes = data
    updatePublishDatalist()

}

async function loadAuthorTags() {

    let r = await fetch("/api/author_tags")
    let data = await r.json()
    allAuthorTags = data
    updateAuthorTagDatalist()

}

function toggleTag(t, e) {

    if (selectedTags.includes(t)) {

        selectedTags = selectedTags.filter(x => x != t)

        e.classList.remove("selected")

    } else {

        selectedTags.push(t)

        e.classList.add("selected")

    }

    syncTagInputFromSelected()
    updateTagDatalist()
    search()

}

function syncTagInputFromSelected() {
    let input = document.getElementById("tags")
    input.value = selectedTags.join(",")
}

function parseTagInput() {
    let input = document.getElementById("tags")
    let raw = input.value
    let endsWithComma = /,\s*$/.test(raw)
    let parts = raw.split(",").map(x => x.trim()).filter(x => x)
    let pending = ""

    if (parts.length > 0 && !endsWithComma) {
        pending = parts[parts.length - 1]
    }

    let committed = parts

    // 搜索标签仅限在库标签
    if (pending && !existingTags.includes(pending)) {
        committed = parts.slice(0, -1)
    }

    return { committed, pending }
}

function syncSelectedFromTagInput() {
    let parsed = parseTagInput()
    selectedTags = parsed.committed

    tagElements.forEach((el, t) => {
        if (selectedTags.includes(t)) {
            el.classList.add("selected")
        } else {
            el.classList.remove("selected")
        }
    })
}

function updateTagDatalist() {
    let list = document.getElementById("tag-options")
    let parsed = parseTagInput()
    let last = parsed.pending.trim().toLowerCase()

    list.innerHTML = ""

    let options = existingTags.filter(t => {
        let v = String(t).toLowerCase()
        return last ? v.includes(last) : true
    }).filter(t => !selectedTags.includes(t))

    options.slice(0, 50).forEach(t => {
        let opt = document.createElement("option")
        opt.value = t
        list.appendChild(opt)
    })
}

function updateTagDatalistSimple(inputId, listId, sourceTags = allTags) {
    let input = document.getElementById(inputId)
    let list = document.getElementById(listId)
    if (!input || !list) return

    let raw = input.value
    let last = raw.split(",").pop().trim().toLowerCase()

    list.innerHTML = ""

    sourceTags.filter(t => {
        let v = String(t).toLowerCase()
        return last ? v.includes(last) : true
    }).slice(0, 50).forEach(t => {
        let opt = document.createElement("option")
        opt.value = t
        list.appendChild(opt)
    })
}

function updatePublishDatalistFor(inputId, listId) {
    let input = document.getElementById(inputId)
    let list = document.getElementById(listId)
    if (!input || !list) return
    let v = input.value.trim().toLowerCase()

    list.innerHTML = ""

    allPublishes.filter(p => {
        let s = String(p).toLowerCase()
        return v ? s.includes(v) : true
    }).slice(0, 50).forEach(p => {
        let opt = document.createElement("option")
        opt.value = p
        list.appendChild(opt)
    })
}

function updatePublishDatalist() {
    updatePublishDatalistFor("publish", "publish-options")
    updatePublishDatalistFor("edit_publish", "publish-options")
}

function updateAuthorTagDatalistFor(inputId, listId) {
    let input = document.getElementById(inputId)
    let list = document.getElementById(listId)
    if (!input || !list) return
    let v = input.value.trim().toLowerCase()

    list.innerHTML = ""

    allAuthorTags.filter(a => {
        let s = String(a).toLowerCase()
        return v ? s.includes(v) : true
    }).slice(0, 50).forEach(a => {
        let opt = document.createElement("option")
        opt.value = a
        list.appendChild(opt)
    })
}

function updateAuthorTagDatalist() {
    updateAuthorTagDatalistFor("author_tag", "author-tag-options")
    updateAuthorTagDatalistFor("edit_author_tag", "author-tag-options")
}

function renderTagChips(containerId, tags, mode) {
    let container = document.getElementById(containerId)
    container.innerHTML = ""
    tags.forEach(t => {
        let chip = document.createElement("span")
        chip.className = "tag-chip"
        chip.innerHTML = `<span>${t}</span><button type="button">×</button>`
        chip.querySelector("button").onclick = () => {
            removeTag(mode, t)
        }
        container.appendChild(chip)
    })
}

function addTag(mode, tag) {
    let t = tag.trim()
    if (!t) return

    let list = mode === "add" ? addTagsList : editTagsList
    if (list.includes(t)) return
    list.push(t)

    if (mode === "add") {
        renderTagChips("add_tags_list", addTagsList, "add")
    } else {
        renderTagChips("edit_tags_list", editTagsList, "edit")
    }
}

function removeTag(mode, tag) {
    let list = mode === "add" ? addTagsList : editTagsList
    let next = list.filter(x => x !== tag)
    if (mode === "add") {
        addTagsList = next
        renderTagChips("add_tags_list", addTagsList, "add")
    } else {
        editTagsList = next
        renderTagChips("edit_tags_list", editTagsList, "edit")
    }
}

function handleTagInput(mode) {
    let inputId = mode === "add" ? "add_tags_input" : "edit_tags_input"
    let input = document.getElementById(inputId)
    let raw = input.value
    if (!raw) return

    if (raw.includes(",")) {
        let parts = raw.split(",")
        parts.slice(0, -1).forEach(p => addTag(mode, p))
        input.value = parts[parts.length - 1].trim()
    }
}

function finalizeTagInput(mode) {
    let inputId = mode === "add" ? "add_tags_input" : "edit_tags_input"
    let input = document.getElementById(inputId)
    let v = input.value.trim()
    if (v) {
        addTag(mode, v)
        input.value = ""
    }
}

async function search() {

    page = 1
    hasMore = true

    document.getElementById("wall").innerHTML = ""

    load()

}

async function load() {

    if (loading) return
    if (!hasMore) return

    loading = true

    let q = document.getElementById("q").value
    let publish = document.getElementById("publish").value
    let author_tag = document.getElementById("author_tag").value
    let author_tag_mode = document.getElementById("author_tag_mode").value

    syncSelectedFromTagInput()

    let tagStr = selectedTags.join(",")

    let pageSize = getPageSize()
    let url = `/api/items?page=${page}` +
        `&page_size=${pageSize}` +
        `&q=${encodeURIComponent(q)}` +
        `&publish=${encodeURIComponent(publish)}` +
        `&author_tag=${encodeURIComponent(author_tag)}` +
        `&author_tag_mode=${encodeURIComponent(author_tag_mode)}` +
        `&tags=${encodeURIComponent(tagStr)}` +
        `&show_img=${show_img}` +
        `&exists_only=${exists_only}`

    let r = await fetch(url)

    let data = await r.json()
    let total = data.total || 0
    data = data.items || []

    let wall = document.getElementById("wall")

    data.forEach(i => {

        let d = document.createElement("div")

        d.className = "card"

        let html = ""

        if (show_img) {
            html = ""
            if (!exists_only) {
                let existsLabel = i.is_exists ? "在库" : "不在库"
                let existsClass = i.is_exists ? "exists-badge" : "exists-badge no"
                html += `<div class="${existsClass}">${existsLabel}</div>`
            }
            if (i.img) {
                let mime = i.img_mime || "image/jpeg"
                html += `<div class="img-frame"><img src="data:${mime};base64,${i.img}"></div>`
            } else {
                html += `<div class="img-frame"></div>`
            }
            html += `<div class="img-title">${i.title}</div>`
            html += `<div>${i.tags.join(",")}</div>`
        } else {
            let existsClass = i.is_exists ? "exists-inline" : "exists-inline no"
            html = `<div class="row-title"><span>${i.title}</span>${!exists_only ? `<div class="${existsClass}">${i.is_exists ? "在库" : "不在库"}</div>` : ""}</div>`
            let publish = i.publish || ""
            let author = i.author || ""
            let authorTag = i.author_tag || ""
            let simpleTitle = i.simple_title || ""
            let remarks = i.remarks || ""
            let customMarks = i.custom_marks || ""
            let safeTags = encodeURIComponent(customMarks)
            let safePublish = encodeURIComponent(publish)
            let safeAuthor = encodeURIComponent(author)
            let safeAuthorTag = encodeURIComponent(authorTag)
            let safeSimpleTitle = encodeURIComponent(simpleTitle)
            let safeRemarks = encodeURIComponent(remarks)
            let safeTitle = encodeURIComponent(i.title || "")
            html += `<div class="row">` +
                `<div class="row-text">` +
                `<div>${publish} ${authorTag} ${simpleTitle} ${remarks} ${customMarks}</div>` +
                `</div>` +
                `<button onclick='openEditModal(${i.id}, "${safeTags}", "${safePublish}", "${safeAuthor}", "${safeAuthorTag}", "${safeSimpleTitle}", "${safeRemarks}", "${safeTitle}", "", "", ${i.is_exists ? 1 : 0})'>编辑</button>` +
                `<button onclick='confirmDelete(${i.id})'>删除</button>` +
                `</div>`
        }

        d.innerHTML = html

        wall.appendChild(d)

        if (show_img) {
            d.style.cursor = "pointer"
            d.onclick = () => {
                let publish = i.publish || ""
                let author = i.author || ""
                let authorTag = i.author_tag || ""
                let simpleTitle = i.simple_title || ""
                let remarks = i.remarks || ""
                let customMarks = i.custom_marks || ""
                openEditModal(
                    i.id,
                    encodeURIComponent(customMarks),
                    encodeURIComponent(publish),
                    encodeURIComponent(author),
                    encodeURIComponent(authorTag),
                    encodeURIComponent(simpleTitle),
                    encodeURIComponent(remarks),
                    encodeURIComponent(i.title || ""),
                    i.img || "",
                    i.img_mime || "",
                    i.is_exists ? 1 : 0
                )
            }
        }

    })

    updateResultSummary(wall.children.length, total)

    if (data.length > 0) page++
    if (data.length === 0 || wall.children.length >= total) {
        hasMore = false
    }

    loading = false

}

function updateResultSummary(shown, total) {
    let box = document.getElementById("resultSummary")
    if (!box) return
    box.innerText = `当前展示 ${shown} 条，总计 ${total} 条`
}

function toggleMode() {

    let body = document.body
    let btn = document.getElementById("modeBtn")

    if (body.classList.contains("mode-simple")) {
        body.classList.remove("mode-simple")
        show_img = true
        btn.innerText = "图墙模式"
    } else {
        body.classList.add("mode-simple")
        show_img = false
        btn.innerText = "简单模式"
    }

    search()

}

function toggleTheme() {
    darkMode = !darkMode
    if (darkMode) {
        document.body.classList.add("dark")
    } else {
        document.body.classList.remove("dark")
    }
    let icon = document.getElementById("themeIcon")
    if (icon) {
        icon.classList.toggle("icon-moon", !darkMode)
        icon.classList.toggle("icon-sun", darkMode)
    }
}

function toggleExists() {
    exists_only = !exists_only
    let btn = document.getElementById("existsBtn")
    if (btn) {
        btn.innerText = exists_only ? "全部" : "只看在库"
    }
    search()
}

window.onscroll = function () {

    if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 400) {

        load()

    }

}

function initInputs() {
    let tagsInput = document.getElementById("tags")
    tagsInput.addEventListener("change", () => {
        syncSelectedFromTagInput()
        search()
    })
    tagsInput.addEventListener("input", () => {
        updateTagDatalist()
    })

    let addTagsInput = document.getElementById("add_tags_input")
    addTagsInput.addEventListener("input", () => {
        handleTagInput("add")
        updateTagDatalistSimple("add_tags_input", "tag-options-add")
    })
    addTagsInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault()
            finalizeTagInput("add")
        }
    })
    addTagsInput.addEventListener("blur", () => {
        finalizeTagInput("add")
    })

    let editTagsInput = document.getElementById("edit_tags_input")
    editTagsInput.addEventListener("input", () => {
        handleTagInput("edit")
        updateTagDatalistSimple("edit_tags_input", "tag-options-edit")
    })
    editTagsInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault()
            finalizeTagInput("edit")
        }
    })
    editTagsInput.addEventListener("blur", () => {
        finalizeTagInput("edit")
    })

    let publishInput = document.getElementById("publish")
    publishInput.addEventListener("input", () => {
        updatePublishDatalist()
    })

    let authorTagInput = document.getElementById("author_tag")
    authorTagInput.addEventListener("input", () => {
        updateAuthorTagDatalist()
    })

    let editPublishInput = document.getElementById("edit_publish")
    if (editPublishInput) {
        editPublishInput.addEventListener("input", () => {
            updatePublishDatalistFor("edit_publish", "publish-options")
        })
    }

    let editAuthorTagInput = document.getElementById("edit_author_tag")
    if (editAuthorTagInput) {
        editAuthorTagInput.addEventListener("input", () => {
            updateAuthorTagDatalistFor("edit_author_tag", "author-tag-options")
        })
    }
}

function initMode() {
    document.body.classList.add("mode-simple")
    show_img = false
    let btn = document.getElementById("modeBtn")
    if (btn) btn.innerText = "简单模式"
}

function clearInput(id) {
    let input = document.getElementById(id)
    if (!input) return

    if (id === "add_tags") {
        addTagsList = []
        renderTagChips("add_tags_list", addTagsList, "add")
        let tagInput = document.getElementById("add_tags_input")
        if (tagInput) tagInput.value = ""
        updateTagDatalistSimple("add_tags_input", "tag-options-add")
        return
    }

    if (id === "edit_tags") {
        editTagsList = []
        renderTagChips("edit_tags_list", editTagsList, "edit")
        let tagInput = document.getElementById("edit_tags_input")
        if (tagInput) tagInput.value = ""
        updateTagDatalistSimple("edit_tags_input", "tag-options-edit")
        return
    }

    if (input.type === "file") {
        input.value = ""
        return
    }

    input.value = ""

    if (id === "add_title") {
        clearAddParseResult()
    }

    if (id === "tags") {
        syncSelectedFromTagInput()
        updateTagDatalist()
    }

    if (id === "publish") {
        updatePublishDatalist()
    }

    if (id === "author_tag") {
        updateAuthorTagDatalist()
    }

    if (id === "edit_publish") {
        updatePublishDatalistFor("edit_publish", "publish-options")
    }

    if (id === "edit_author_tag") {
        updateAuthorTagDatalistFor("edit_author_tag", "author-tag-options")
    }
}

function openAddModal() {
    let modal = document.getElementById("addModal")
    modal.classList.add("open")
    addTagsList = []
    renderTagChips("add_tags_list", addTagsList, "add")
    let addTagsInput = document.getElementById("add_tags_input")
    if (addTagsInput) addTagsInput.value = ""
    clearAddParseResult()
    let titleInput = document.getElementById("add_title")
    titleInput.focus()
}

function closeAddModal(e) {
    let modal = document.getElementById("addModal")
    if (!e || e.target === modal) {
        modal.classList.remove("open")
    }
}

function openEditModal(id, tags, publish, author, authorTag, simpleTitle, remarks, title, thumb, thumbMime, isExists) {
    editingItemId = id
    let modal = document.getElementById("editModal")
    modal.classList.add("open")
    let decoded = tags ? decodeURIComponent(tags) : ""
    editTagsList = decoded ? decoded.split(",").map(x => x.trim()).filter(x => x) : []
    renderTagChips("edit_tags_list", editTagsList, "edit")
    let tagsInput = document.getElementById("edit_tags_input")
    tagsInput.value = ""
    let imgInput = document.getElementById("edit_img")
    imgInput.value = ""

    let publishInput = document.getElementById("edit_publish")
    let authorInput = document.getElementById("edit_author")
    let authorTagInput = document.getElementById("edit_author_tag")
    let simpleTitleInput = document.getElementById("edit_simple_title")
    let remarksInput = document.getElementById("edit_remarks")
    let titleInput = document.getElementById("edit_title")
    let thumbWrap = document.getElementById("edit_thumb_wrap")
    let thumbImg = document.getElementById("edit_thumb")
    let modalBody = document.getElementById("edit_modal_body")
    let sideActions = document.getElementById("edit_side_actions")
    let existsSelect = document.getElementById("edit_is_exists")

    if (publishInput) publishInput.value = publish ? decodeURIComponent(publish) : ""
    if (authorInput) authorInput.value = author ? decodeURIComponent(author) : ""
    if (authorTagInput) authorTagInput.value = authorTag ? decodeURIComponent(authorTag) : ""
    if (simpleTitleInput) simpleTitleInput.value = simpleTitle ? decodeURIComponent(simpleTitle) : ""
    if (remarksInput) remarksInput.value = remarks ? decodeURIComponent(remarks) : ""
    if (titleInput) titleInput.value = title ? decodeURIComponent(title) : ""
    if (existsSelect) existsSelect.value = String(isExists === 0 || isExists === "0" ? 0 : 1)

    if (thumbWrap && thumbImg && modalBody && sideActions) {
        if (thumb) {
            let mime = thumbMime || "image/jpeg"
            thumbImg.src = `data:${mime};base64,${thumb}`
            thumbWrap.classList.remove("disabled")
            thumbWrap.onclick = () => openImageModal(editingItemId)
            thumbWrap.classList.remove("hidden")
            modalBody.classList.remove("single")
            sideActions.classList.remove("hidden")
        } else {
            thumbImg.removeAttribute("src")
            thumbWrap.classList.add("disabled")
            thumbWrap.onclick = null
            thumbWrap.classList.add("hidden")
            modalBody.classList.add("single")
            sideActions.classList.add("hidden")
        }
    }
}

function closeEditModal(e) {
    let modal = document.getElementById("editModal")
    if (!e || e.target === modal) {
        modal.classList.remove("open")
    }
}

async function submitEdit() {
    if (!editingItemId) return

    let imgInput = document.getElementById("edit_img")
    let publishInput = document.getElementById("edit_publish")
    let authorInput = document.getElementById("edit_author")
    let authorTagInput = document.getElementById("edit_author_tag")
    let simpleTitleInput = document.getElementById("edit_simple_title")
    let remarksInput = document.getElementById("edit_remarks")
    let existsSelect = document.getElementById("edit_is_exists")

    let form = new FormData()
    form.append("item_id", String(editingItemId))
    form.append("publish", publishInput ? publishInput.value.trim() : "")
    form.append("author", authorInput ? authorInput.value.trim() : "")
    form.append("author_tag", authorTagInput ? authorTagInput.value.trim() : "")
    form.append("simple_title", simpleTitleInput ? simpleTitleInput.value.trim() : "")
    form.append("remarks", remarksInput ? remarksInput.value.trim() : "")
    form.append("is_exists", existsSelect ? existsSelect.value : "1")
    form.append("tags", editTagsList.join(","))

    if (imgInput.files && imgInput.files.length > 0) {
        form.append("img", imgInput.files[0])
    }

    let r = await fetch("/api/update", {
        method: "POST",
        body: form
    })

    let data = await r.json()
    if (data && data.ok && data.item) {
        closeEditModal()
        await loadTags()
        await loadPublishes()
        await loadAuthorTags()
        // 局部更新卡片
        updateWallItem(data.item)
    } else {
        alert("update failed")
    }
}

async function addItem() {
    let titleInput = document.getElementById("add_title")
    let imgInput = document.getElementById("add_img")

    let title = titleInput.value.trim()
    if (!title) {
        alert("title required")
        titleInput.focus()
        return
    }

    let form = new FormData()
    form.append("title", title)
    form.append("tags", addTagsList.join(","))

    if (imgInput.files && imgInput.files.length > 0) {
        form.append("img", imgInput.files[0])
    }

    let r = await fetch("/api/add", {
        method: "POST",
        body: form
    })

    let data = await r.json()
    if (data && data.ok) {
        closeAddModal()
        search()
    } else {
        if (data && data.error === "TITLE_EXISTS") {
            alert("title 已存在")
            titleInput.focus()
        } else {
            alert("add failed")
        }
    }
}

// 局部更新卡片
function updateWallItem(item) {
    let wall = document.getElementById("wall")
    if (!wall) return
    let cards = wall.getElementsByClassName("card")
    for (let card of cards) {
        if (card.dataset.id == item.id) {
            let html = renderCardHtml(item)
            card.innerHTML = html
            // 重新绑定点击事件
            if (show_img) {
                card.style.cursor = "pointer"
                card.onclick = () => {
                    let i = item
                    let publish = i.publish || ""
                    let author = i.author || ""
                    let authorTag = i.author_tag || ""
                    let simpleTitle = i.simple_title || ""
                    let remarks = i.remarks || ""
                    let customMarks = i.custom_marks || ""
                    openEditModal(
                        i.id,
                        encodeURIComponent(customMarks),
                        encodeURIComponent(publish),
                        encodeURIComponent(author),
                        encodeURIComponent(authorTag),
                        encodeURIComponent(simpleTitle),
                        encodeURIComponent(remarks),
                        encodeURIComponent(i.title || ""),
                        i.img || "",
                        i.img_mime || "",
                        i.is_exists ? 1 : 0
                    )
                }
            }
            break
        }
    }
}

// 局部插入新卡片
function insertWallItem(item) {
    let wall = document.getElementById("wall")
    if (!wall) return
    let d = document.createElement("div")
    d.className = "card"
    d.dataset.id = item.id
    d.innerHTML = renderCardHtml(item)
    if (show_img) {
        d.style.cursor = "pointer"
        d.onclick = () => {
            let i = item
            let publish = i.publish || ""
            let author = i.author || ""
            let authorTag = i.author_tag || ""
            let simpleTitle = i.simple_title || ""
            let remarks = i.remarks || ""
            let customMarks = i.custom_marks || ""
            openEditModal(
                i.id,
                encodeURIComponent(customMarks),
                encodeURIComponent(publish),
                encodeURIComponent(author),
                encodeURIComponent(authorTag),
                encodeURIComponent(simpleTitle),
                encodeURIComponent(remarks),
                encodeURIComponent(i.title || ""),
                i.img || "",
                i.img_mime || "",
                i.is_exists ? 1 : 0
            )
        }
    }
    wall.insertBefore(d, wall.firstChild)
}

// 渲染卡片html
function renderCardHtml(i) {
    let html = ""
    if (show_img) {
        html = ""
        if (!exists_only) {
            let existsLabel = i.is_exists ? "在库" : "不在库"
            let existsClass = i.is_exists ? "exists-badge" : "exists-badge no"
            html += `<div class="${existsClass}">${existsLabel}</div>`
        }
        if (i.img) {
            let mime = i.img_mime || "image/jpeg"
            html += `<div class="img-frame"><img src="data:${mime};base64,${i.img}"></div>`
        } else {
            html += `<div class="img-frame"></div>`
        }
        html += `<div class="img-title">
            ${i.title}
        </div>`
        html += `<div>${(i.tags || []).join(",")}</div>`
    } else {
        let existsClass = i.is_exists ? "exists-inline" : "exists-inline no"
        html = `<div class="row-title"><span>${i.title}</span>${!exists_only ? `<div class="${existsClass}">${i.is_exists ? "在库" : "不在库"}</div>` : ""}</div>`
        let publish = i.publish || ""
        let author = i.author || ""
        let authorTag = i.author_tag || ""
        let simpleTitle = i.simple_title || ""
        let remarks = i.remarks || ""
        let customMarks = i.custom_marks || ""
        let safeTags = encodeURIComponent(customMarks)
        let safePublish = encodeURIComponent(publish)
        let safeAuthor = encodeURIComponent(author)
        let safeAuthorTag = encodeURIComponent(authorTag)
        let safeSimpleTitle = encodeURIComponent(simpleTitle)
        let safeRemarks = encodeURIComponent(remarks)
        let safeTitle = encodeURIComponent(i.title || "")
        html += `<div class="row">` +
            `<div class="row-text">` +
            `<div>${publish} ${authorTag} ${simpleTitle} ${remarks} ${customMarks}</div>` +
            `</div>` +
            `<button onclick='openEditModal(${i.id}, "${safeTags}", "${safePublish}", "${safeAuthor}", "${safeAuthorTag}", "${safeSimpleTitle}", "${safeRemarks}", "${safeTitle}", "", "", ${i.is_exists ? 1 : 0})'>编辑</button>` +
            `<button onclick='confirmDelete(${i.id})'>删除</button>` +
            `</div>`
    }
    return html
}

function confirmDelete(itemId) {
    if (!itemId) return
    pendingDeleteId = itemId
    openDeleteModal()
}

async function deleteItem(itemId) {
    let form = new FormData()
    form.append("item_id", String(itemId))
    let r = await fetch("/api/delete", {
        method: "POST",
        body: form
    })
    let data = await r.json()
    if (data && data.ok) {
        closeEditModal()
        await loadTags()
        await loadPublishes()
        await loadAuthorTags()
        search()
    } else {
        alert("delete failed")
    }
}

function openImageModal(itemId) {
    let modal = document.getElementById("imageModal")
    let img = document.getElementById("original_img")
    if (!modal || !img || !itemId) return
    img.src = `/api/item_img?item_id=${itemId}`
    modal.classList.add("open")
}

function closeImageModal() {
    let modal = document.getElementById("imageModal")
    if (modal) modal.classList.remove("open")
    let img = document.getElementById("original_img")
    if (img) img.removeAttribute("src")
}

function openDeleteModal() {
    let modal = document.getElementById("deleteModal")
    if (modal) modal.classList.add("open")
}

function closeDeleteModal(e) {
    let modal = document.getElementById("deleteModal")
    if (!modal) return
    if (!e || e.target === modal) {
        modal.classList.remove("open")
        pendingDeleteId = null
    }
}

function confirmDeleteAction() {
    if (!pendingDeleteId) {
        closeDeleteModal()
        return
    }
    let id = pendingDeleteId
    closeDeleteModal()
    deleteItem(id)
}

function clearAddParseResult() {
    let box = document.getElementById("add_parse_result")
    if (!box) return
    box.innerHTML = ""
    box.classList.add("hidden")
}

function renderAddParseResult(data) {
    let box = document.getElementById("add_parse_result")
    if (!box) return

    let publish = data.publish || "-"
    let author = data.author || "-"
    let authorTag = data.author_tag || "-"
    let title = data.title || "-"
    let remarks = Array.isArray(data.remarks) && data.remarks.length > 0 ? data.remarks.join(", ") : "-"

    box.innerHTML =
        `<div class="parse-item"><span class="parse-label">出版</span><span>${publish}</span></div>` +
        `<div class="parse-item"><span class="parse-label">作者</span><span>${author}</span></div>` +
        `<div class="parse-item"><span class="parse-label">作者标签</span><span>${authorTag}</span></div>` +
        `<div class="parse-item"><span class="parse-label">标题</span><span>${title}</span></div>` +
        `<div class="parse-item"><span class="parse-label">备注</span><span>${remarks}</span></div>`

    box.classList.remove("hidden")
}

async function parseAddTitle() {
    let titleInput = document.getElementById("add_title")
    let title = titleInput.value.trim()
    if (!title) {
        alert("title required")
        titleInput.focus()
        return
    }

    let btn = document.getElementById("add_parse_btn")
    if (btn) btn.disabled = true

    try {
        let form = new FormData()
        form.append("title", title)
        let r = await fetch("/api/parse_title", {
            method: "POST",
            body: form
        })
        let data = await r.json()
        renderAddParseResult(data)
    } catch (e) {
        alert("parse failed")
    } finally {
        if (btn) btn.disabled = false
    }
}

loadTags()
loadPublishes()
loadAuthorTags()

initInputs()
initMode()

search()
